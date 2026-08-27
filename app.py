import os
import json
import re
import time
import tempfile
import ast
import requests
import streamlit as st
import pandas as pd
import numpy as np
import google.cloud.firestore as firestore
import google.auth.transport.requests
from google.oauth2 import service_account
from google import genai
from supabase import create_client
from pypdf import PdfReader

# ---------------- PAGE CONFIG & STYLING ----------------
st.set_page_config(
    page_title="SMSF Audit Hub | Enterprise Portal",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif; background-color: #F8FAFC; }
    .hero-banner { background: linear-gradient(135deg, #0F172A 0%, #1E293B 50%, #1E40AF 100%); padding: 2rem 2rem; border-radius: 20px; color: white; margin-bottom: 1.5rem; }
    .hero-title { font-size: 2.2rem; font-weight: 800; margin-bottom: 0.2rem; }
    .hero-subtitle { font-size: 0.95rem; color: #94A3B8; font-weight: 400; }
    .glass-card { background: rgba(255, 255, 255, 0.95); border: 1px solid #E2E8F0; border-radius: 16px; padding: 1.5rem; margin-bottom: 1.25rem; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.03); }
    .metric-box { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 14px; padding: 1.25rem; text-align: left; }
    .metric-value { font-size: 2.1rem; font-weight: 800; color: #0F172A; }
    .metric-label { font-size: 0.8rem; font-weight: 600; color: #64748B; text-transform: uppercase; }
    .badge-unqualified { background: #DCFCE7; color: #15803D; font-size: 0.75rem; font-weight: 700; padding: 4px 12px; border-radius: 30px; border: 1px solid #86EFAC; }
    .badge-qualified { background: #FEE2E2; color: #B91C1C; font-size: 0.75rem; font-weight: 700; padding: 4px 12px; border-radius: 30px; border: 1px solid #FCA5A5; }
    .sub-doc-pill { background: #F1F5F9; border: 1px solid #CBD5E1; border-radius: 8px; padding: 8px 12px; margin-top: 6px; font-size: 0.82rem; }
</style>
""", unsafe_allow_html=True)


# ---------------- INITIALIZE CONNECTIONS ----------------
@st.cache_resource(ttl=600)
def init_services():
    db = None
    cred_dict = None
    if "gcp_service_account" in st.secrets and "textkey" in st.secrets["gcp_service_account"]:
        try:
            cred_dict = json.loads(st.secrets["gcp_service_account"]["textkey"])
            project_id = cred_dict.get("project_id")
            
            # Explicitly parse credentials with GCP cloud-platform scope
            credentials = service_account.Credentials.from_service_account_info(
                cred_dict,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            db = firestore.Client(project=project_id, credentials=credentials)
        except Exception as e:
            st.sidebar.error(f"Firestore Client Init Error: {e}")

    supabase = None
    sb_url = st.secrets.get("SUPABASE_URL", "")
    sb_key = st.secrets.get("SUPABASE_KEY", "")
    if sb_url and sb_key:
        try:
            supabase = create_client(sb_url, sb_key)
        except Exception as e:
            st.sidebar.error(f"Supabase Auth Error: {e}")

    return db, supabase, cred_dict

db, supabase, cred_dict = init_services()


# ---------------- FIRESTORE REST HELPERS ----------------
def parse_firestore_value(val_dict):
    """Converts a Firestore REST API field object into a native Python object."""
    if not isinstance(val_dict, dict):
        return val_dict
    if "stringValue" in val_dict:
        return val_dict["stringValue"]
    elif "integerValue" in val_dict:
        return int(val_dict["integerValue"])
    elif "doubleValue" in val_dict:
        return float(val_dict["doubleValue"])
    elif "booleanValue" in val_dict:
        return val_dict["booleanValue"]
    elif "timestampValue" in val_dict:
        return val_dict["timestampValue"]
    elif "arrayValue" in val_dict:
        values = val_dict["arrayValue"].get("values", [])
        return [parse_firestore_value(v) for v in values]
    elif "mapValue" in val_dict:
        fields = val_dict["mapValue"].get("fields", {})
        return {k: parse_firestore_value(v) for k, v in fields.items()}
    elif "nullValue" in val_dict:
        return None
    return next(iter(val_dict.values()), "") if val_dict else ""


# ---------------- PDF TEXT EXTRACTION HELPER ----------------
def extract_pdf_content(file_path):
    """Extracts raw text from PDF files for backfilling and multi-field indexing."""
    try:
        reader = PdfReader(file_path)
        return " ".join([page.extract_text() or "" for page in reader.pages])
    except Exception as e:
        st.error(f"Extraction error: {e}")
        return ""


# ---------------- DATA FETCHERS & HELPERS ----------------
@st.cache_data(ttl=300)
def fetch_reports():
    # Attempt 1: Standard SDK fetch
    if db:
        try:
            docs = db.collection('type2_reports').get()
            return [d.to_dict() for d in docs if d.exists]
        except Exception:
            pass  # Fallback to REST API below if SDK fails

    # Attempt 2: Direct REST API Fallback
    if cred_dict:
        try:
            project_id = cred_dict.get("project_id")
            credentials = service_account.Credentials.from_service_account_info(
                cred_dict,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            token = credentials.token
            
            url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/type2_reports"
            headers = {"Authorization": f"Bearer {token}"}
            
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                reports = []
                for doc in data.get("documents", []):
                    fields = doc.get("fields", {})
                    parsed = {k: parse_firestore_value(v) for k, v in fields.items()}
                    reports.append(parsed)
                return reports
            else:
                st.error(f"REST Fetch Error ({resp.status_code}): {resp.text}")
        except Exception as ex:
            st.error(f"Error loading compliance reports: {ex}")
            
    return []

@st.cache_data(ttl=300)
def fetch_properties():
    if not supabase:
        return pd.DataFrame()
    try:
        response = supabase.table("property_register").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def fetch_unlisted():
    if not supabase:
        return pd.DataFrame()
    try:
        response = supabase.table("unlisted_register").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception:
        return pd.DataFrame()

def robust_json_decode(text):
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                try:
                    return ast.literal_eval(match.group(0))
                except Exception:
                    pass
    return None

def save_report_metadata(metadata):
    """Saves report metadata via SDK, falling back to REST POST if SDK fails."""
    if db:
        try:
            db.collection('type2_reports').add(metadata)
            return True
        except Exception:
            pass

    if cred_dict:
        try:
            project_id = cred_dict.get("project_id")
            credentials = service_account.Credentials.from_service_account_info(
                cred_dict,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            token = credentials.token
            
            url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/type2_reports"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            
            fields_payload = {}
            for k, v in metadata.items():
                if isinstance(v, (int, float)):
                    fields_payload[k] = {"doubleValue": float(v)}
                elif isinstance(v, bool):
                    fields_payload[k] = {"booleanValue": v}
                else:
                    fields_payload[k] = {"stringValue": str(v if v is not None else "")}
            
            resp = requests.post(url, headers=headers, json={"fields": fields_payload}, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            st.error(f"REST Write Error: {e}")
            return False
    return False


# ---------------- NAVIGATION SIDEBAR ----------------
st.sidebar.title("🛡️ Audit Portal")
app_mode = st.sidebar.radio("Navigate", ["🔍 Search & Analytics Hub", "📤 AI & Database Admin Studio"])

api_key = st.secrets.get("GEMINI_API_KEY", "")


# ---------------- MODE 1: SEARCH & ANALYTICS HUB ----------------
if app_mode == "🔍 Search & Analytics Hub":
    tab1, tab2, tab3 = st.tabs(["📄 PDF Compliance Hub", "🏢 Property Register", "📈 Unlisted Investment Register"])

    # --- TAB 1: PDF COMPLIANCE HUB ---
    with tab1:
        st.markdown("""
        <div class="hero-banner">
            <div class="hero-title">SMSF Verification Engine</div>
            <div class="hero-subtitle">Real-time GS007, SOC 1, and ASAE 3402 Compliance Intelligence</div>
        </div>
        """, unsafe_allow_html=True)

        reports = fetch_reports()

        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(f'<div class="metric-box"><div class="metric-label">Indexed Documents</div><div class="metric-value">{len(reports)}</div></div>', unsafe_allow_html=True)
        clean_opinions = sum(1 for r in reports if 'unqualified' in str(r.get('audit_opinion', '')).lower())
        m2.markdown(f'<div class="metric-box"><div class="metric-label">Unqualified Reports</div><div class="metric-value" style="color:#16A34A;">{clean_opinions}</div></div>', unsafe_allow_html=True)
        exceptions = len(reports) - clean_opinions
        m3.markdown(f'<div class="metric-box"><div class="metric-label">Exceptions Flagged</div><div class="metric-value" style="color:#DC2626;">{exceptions}</div></div>', unsafe_allow_html=True)
        fy25 = sum(1 for r in reports if 'FY2025' in str(r.get('aus_financial_year', '')) or '2025' in str(r.get('financial_year', '')))
        m4.markdown(f'<div class="metric-box"><div class="metric-label">FY2025 Reports</div><div class="metric-value" style="color:#2563EB;">{fy25}</div></div>', unsafe_allow_html=True)

        st.write("")
        fcol1, fcol2, fcol3, fcol4 = st.columns([2, 1, 1, 1])
        with fcol1:
            q = st.text_input("🔍 Keyword Search (Filename, Platform, Auditor, Content)", "").strip().lower()
        with fcol2:
            fy_options = ["All Years"] + [f"FY{year}" for year in range(2021, 2031)]
            fy_sel = st.selectbox("Financial Year", fy_options)
        with fcol3:
            status_sel = st.selectbox("Audit Status Filter", ["All Reports", "Qualified Only", "Unqualified Only"])
        with fcol4:
            sort_order = st.selectbox("Sort Alphabetically", ["A-Z (Ascending)", "Z-A (Descending)"])

        # Multi-field query filtering across original filename, display titles, extracted text, and platforms
        filtered = []
        for r in reports:
            search_blob = f"{r.get('platform_name', '')} {r.get('display_title', '')} {r.get('source_filename', '')} {r.get('original_filename', '')} {r.get('auditing_firm', '')} {r.get('audit_opinion', '')} {r.get('key_exceptions_summary', '')} {r.get('extracted_content', '')}".lower()
            matches_search = (q in search_blob) if q else True
            doc_fy = f"{r.get('aus_financial_year', '')} {r.get('financial_year', '')}".upper()
            matches_fy = True if fy_sel == "All Years" else (fy_sel.replace("FY", "") in doc_fy)
            opinion_str = str(r.get('audit_opinion', '')).lower()
            matches_status = True
            if status_sel == "Qualified Only":
                matches_status = "qualified" in opinion_str and "unqualified" not in opinion_str
            elif status_sel == "Unqualified Only":
                matches_status = "unqualified" in opinion_str

            if matches_search and matches_fy and matches_status:
                filtered.append(r)

        grouped_reports = {}
        for r in filtered:
            group_key = f"{r.get('platform_name', 'Unknown Platform')} - {r.get('aus_financial_year', r.get('financial_year', 'FY2025'))}"
            if group_key not in grouped_reports:
                grouped_reports[group_key] = []
            grouped_reports[group_key].append(r)

        reverse_sort = (sort_order == "Z-A (Descending)")
        sorted_group_keys = sorted(grouped_reports.keys(), key=lambda x: x.lower(), reverse=reverse_sort)

        st.write("")
        st.markdown("<b>🔤 Quick Alphabet Filter:</b>", unsafe_allow_html=True)
        letters = ["ALL"] + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        selected_letter = st.radio("A-Z Bar", letters, horizontal=True, label_visibility="collapsed")

        if selected_letter != "ALL":
            sorted_group_keys = [k for k in sorted_group_keys if k.strip().upper().startswith(selected_letter)]

        st.divider()
        st.markdown(f"Showing **{len(sorted_group_keys)}** Compliance Packages ({len(filtered)} total documents):")

        for group_key in sorted_group_keys:
            doc_list = grouped_reports[group_key]
            primary_doc = doc_list[0]
            platform_name = primary_doc.get('platform_name', 'Unknown Platform')
            aus_fy = primary_doc.get('aus_financial_year', primary_doc.get('financial_year', 'FY2025'))
            has_qualified = any("qualified" in str(d.get('audit_opinion', '')).lower() and "unqualified" not in str(d.get('audit_opinion', '')).lower() for d in doc_list)
            overall_opinion = "QUALIFIED" if has_qualified else "UNQUALIFIED"
            badge_class = "badge-qualified" if has_qualified else "badge-unqualified"

            st.markdown(f"""
            <div class="glass-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <h3 style="margin:0; color:#0F172A; font-weight:700;">🏢 {platform_name} &nbsp;<span style="color:#2563EB; font-size:1.1rem;">({aus_fy} Compliance File)</span></h3>
                    <span class="{badge_class}">{overall_opinion}</span>
                </div>
                <p style="color:#64748B; font-size:0.88rem; margin: 8px 0 14px 0;">
                    <strong>Auditor:</strong> {primary_doc.get('auditing_firm', 'N/A')} &nbsp;•&nbsp; 
                    <strong>Sub-documents Attached:</strong> {len(doc_list)}
                </p>
            """, unsafe_allow_html=True)
            
            for d in doc_list:
                role_tag = f"<b>[{d.get('doc_role', 'Control Report')}]</b> " if d.get('doc_role') else ""
                date_range = f" ({d.get('date_coverage_period', '')})" if d.get('date_coverage_period') else ""
                col_left, col_mid, col_right = st.columns([3, 1, 1])
                
                filename_display = d.get('source_filename', d.get('original_filename', 'Report.pdf'))
                view_target_url = d.get('view_url', d.get('download_url', '#'))
                download_target_url = d.get('download_url', '#')

                with col_left:
                    st.markdown(f"""
                    <div class="sub-doc-pill">
                        📄 {role_tag}<strong>{filename_display}</strong>{date_range}<br/>
                        <span style="color:#475569;">Exceptions: {d.get('key_exceptions_summary', 'None flagged')}</span>
                    </div>
                    """, unsafe_allow_html=True)
                with col_mid:
                    if view_target_url != '#':
                        st.link_button("👁️ View", view_target_url, use_container_width=True)
                with col_right:
                    if download_target_url != '#':
                        st.link_button("📥 Download", download_target_url, use_container_width=True)
            
            st.markdown("</div>", unsafe_allow_html=True)

    # --- TAB 2: PROPERTY REGISTER ---
    with tab2:
        st.markdown("""
        <div class="hero-banner">
            <div class="hero-title">Property Audit Register</div>
            <div class="hero-subtitle">Permanently stored cloud database for properties across financial years</div>
        </div>
        """, unsafe_allow_html=True)

        df_prop = fetch_properties()

        if not df_prop.empty:
            p1, p2, p3, p4 = st.columns(4)
            p1.markdown(f'<div class="metric-box"><div class="metric-label">Total Stored Properties</div><div class="metric-value">{len(df_prop)}</div></div>', unsafe_allow_html=True)
            years = df_prop['audit_year_end'].dropna().astype(str).unique() if 'audit_year_end' in df_prop.columns else []
            p2.markdown(f'<div class="metric-box"><div class="metric-label">Audit Years Covered</div><div class="metric-value" style="color:#2563EB;">{len(years)}</div></div>', unsafe_allow_html=True)
            states = df_prop['state'].dropna().astype(str).unique() if 'state' in df_prop.columns else []
            p3.markdown(f'<div class="metric-box"><div class="metric-label">States / Regions</div><div class="metric-value">{len(states)}</div></div>', unsafe_allow_html=True)
            types = df_prop['type_of_property'].dropna().astype(str).unique() if 'type_of_property' in df_prop.columns else []
            p4.markdown(f'<div class="metric-box"><div class="metric-label">Property Types</div><div class="metric-value">{len(types)}</div></div>', unsafe_allow_html=True)

            st.write("")
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                sel_year = st.multiselect("Audit Year End", sorted([str(y) for y in years]))
            with f2:
                sel_state = st.multiselect("State", sorted([str(s) for s in states]))
            with f3:
                sel_type = st.multiselect("Type of Property", sorted([str(t) for t in types]))
            with f4:
                search_addr = st.text_input("🔍 Search Address / Suburb", "").strip().lower()

            filtered_p = df_prop.copy()
            if sel_year:
                filtered_p = filtered_p[filtered_p['audit_year_end'].astype(str).isin(sel_year)]
            if sel_state:
                filtered_p = filtered_p[filtered_p['state'].astype(str).isin(sel_state)]
            if sel_type:
                filtered_p = filtered_p[filtered_p['type_of_property'].astype(str).isin(sel_type)]
            if search_addr:
                mask = filtered_p.apply(lambda row: search_addr in str(row.values).lower(), axis=1)
                filtered_p = filtered_p[mask]

            st.markdown(f"Displaying **{len(filtered_p)}** of **{len(df_prop)}** stored property records:")
            st.dataframe(filtered_p, use_container_width=True)
        else:
            st.info("No records currently stored in `property_register`. Go to 'AI & Database Admin Studio' to perform a cloud sync.")

    # --- TAB 3: UNLISTED REGISTER ---
    with tab3:
        st.markdown("""
        <div class="hero-banner">
            <div class="hero-title">Unlisted Investment Register</div>
            <div class="hero-subtitle">Permanently stored cloud database for unlisted entities and valuations</div>
        </div>
        """, unsafe_allow_html=True)

        df_unlisted = fetch_unlisted()

        if not df_unlisted.empty:
            u1, u2, u3, u4 = st.columns(4)
            u1.markdown(f'<div class="metric-box"><div class="metric-label">Total Stored Entities</div><div class="metric-value">{len(df_unlisted)}</div></div>', unsafe_allow_html=True)
            u_years = df_unlisted['year'].dropna().astype(str).unique() if 'year' in df_unlisted.columns else []
            u2.markdown(f'<div class="metric-box"><div class="metric-label">Financial Years</div><div class="metric-value" style="color:#2563EB;">{len(u_years)}</div></div>', unsafe_allow_html=True)
            structures = df_unlisted['structure'].dropna().astype(str).unique() if 'structure' in df_unlisted.columns else []
            u3.markdown(f'<div class="metric-box"><div class="metric-label">Entity Structures</div><div class="metric-value">{len(structures)}</div></div>', unsafe_allow_html=True)
            holding_types = df_unlisted['widely_closely_held'].dropna().astype(str).unique() if 'widely_closely_held' in df_unlisted.columns else []
            u4.markdown(f'<div class="metric-box"><div class="metric-label">Holding Status Types</div><div class="metric-value">{len(holding_types)}</div></div>', unsafe_allow_html=True)

            st.write("")
            uf1, uf2, uf3, uf4 = st.columns(4)
            with uf1:
                u_sel_year = st.multiselect("Year", sorted([str(y) for y in u_years]))
            with uf2:
                u_sel_struct = st.multiselect("Structure", sorted([str(s) for s in structures]))
            with uf3:
                u_sel_holding = st.multiselect("Widely/Closely Held", sorted([str(h) for h in holding_types]))
            with uf4:
                search_entity = st.text_input("🔍 Search Entity Name / Director", "").strip().lower()

            filtered_u = df_unlisted.copy()
            if u_sel_year:
                filtered_u = filtered_u[filtered_u['year'].astype(str).isin(u_sel_year)]
            if u_sel_struct:
                filtered_u = filtered_u[filtered_u['structure'].astype(str).isin(u_sel_struct)]
            if u_sel_holding:
                filtered_u = filtered_u[filtered_u['widely_closely_held'].astype(str).isin(u_sel_holding)]
            if search_entity:
                mask = filtered_u.apply(lambda row: search_entity in str(row.values).lower(), axis=1)
                filtered_u = filtered_u[mask]

            st.markdown(f"Displaying **{len(filtered_u)}** of **{len(df_unlisted)}** stored entity records:")
            st.dataframe(filtered_u, use_container_width=True)
        else:
            st.info("No records currently stored in `unlisted_register`. Go to 'AI & Database Admin Studio' to perform a cloud sync.")


# ---------------- MODE 2: ADMIN & UPLOAD STUDIO ----------------
elif app_mode == "📤 AI & Database Admin Studio":
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">Admin Management & Upload Studio</div>
        <div class="hero-subtitle">Upload PDF reports or sync Excel registers to the permanent cloud database</div>
    </div>
    """, unsafe_allow_html=True)

    admin_tab1, admin_tab2 = st.tabs(["📊 Register Data Cloud Sync", "📄 PDF Batch Uploader"])

    # --- ADMIN TAB 1: CSV REGISTER SYNC ---
    with admin_tab1:
        st.subheader("Cloud Register Ingestion")
        st.caption("Upload your master CSV files to permanently store records in Supabase.")

        col_p, col_u = st.columns(2)

        # Property Sync
        with col_p:
            st.markdown("#### 🏢 Property Register Sync")
            prop_file = st.file_uploader("Select `Property Database.csv`", type=["csv"], key="sync_p")
            overwrite_prop = st.checkbox("Clear existing property database before upload", value=False, key="overwrite_p")
            
            if prop_file and st.button("🚀 Sync Property Database to Supabase", type="primary"):
                if not supabase:
                    st.error("Supabase connection missing in secrets.")
                else:
                    try:
                        df = pd.read_csv(prop_file, encoding='latin1')
                        column_mapping = {
                            'Audit Year End': 'audit_year_end',
                            'Address of Property': 'address_of_property',
                            'Suburb': 'suburb',
                            'State': 'state',
                            'Type of Property': 'type_of_property',
                            'Use of Property': 'use_of_property',
                            'Land Area': 'land_area',
                            'Measurement': 'measurement',
                            'Floor Area': 'floor_area',
                            'MV': 'mv',
                            'Basis of MV -Appraisal/Valuation/CoreLogic': 'basis_of_mv',
                            'Date of Appraisal/Valuation': 'date_of_appraisal_valuation',
                            'Comparable Data': 'comparable_data',
                            'Transaction during the year': 'transaction_during_year',
                            'Market Rent per annum': 'market_rent_pa',
                            'Market Rent per m2': 'market_rent_sqm',
                            'ROR': 'ror',
                            'Notes': 'notes'
                        }
                        df = df.rename(columns=column_mapping)
                        
                        df = df.replace([np.inf, -np.inf], None)
                        df = df.astype(object).where(pd.notnull(df), None)
                        records = df.to_dict(orient='records')

                        if overwrite_prop:
                            supabase.table('property_register').delete().neq('id', 0).execute()

                        batch_size = 300
                        for i in range(0, len(records), batch_size):
                            batch = records[i:i + batch_size]
                            supabase.table('property_register').insert(batch).execute()

                        st.cache_data.clear()
                        st.success(f"✅ Successfully synced {len(records)} Property records to Supabase!")
                    except Exception as e:
                        st.error(f"Sync failed: {e}")

        # Unlisted Sync
        with col_u:
            st.markdown("#### 📈 Unlisted Entity Register Sync")
            unlisted_file = st.file_uploader("Select `Unlisted Entity Database.csv`", type=["csv"], key="sync_u")
            overwrite_unlisted = st.checkbox("Clear existing unlisted database before upload", value=False, key="overwrite_u")
            
            if unlisted_file and st.button("🚀 Sync Unlisted Database to Supabase", type="primary"):
                if not supabase:
                    st.error("Supabase connection missing in secrets.")
                else:
                    try:
                        df = pd.read_csv(unlisted_file, encoding='latin1')
                        if "Unnamed: 12" in df.columns:
                            df = df.drop(columns=["Unnamed: 12"])

                        column_mapping = {
                            'Year': 'year',
                            'Name of Unlisted Entity': 'entity_name',
                            'Entity FS Year End': 'entity_fs_year_end',
                            'Structure': 'structure',
                            'Notes': 'notes',
                            'Widely/Closely Held': 'widely_closely_held',
                            'ASIC Search (for Closely Held)': 'asic_search',
                            'Names of Directors': 'names_of_directors',
                            'MV per unit': 'mv_per_unit',
                            'Basis of valuation (NTA, capital raising, director assessment etc)': 'basis_of_valuation',
                            'Audit conclusion (ACR, other matter, qualfied part A, B)': 'audit_conclusion',
                            'Note/Links': 'note_links'
                        }
                        df = df.rename(columns=column_mapping)
                        
                        if 'entity_name' in df.columns:
                            df['entity_name'] = df['entity_name'].astype(str).str.strip()
                        if 'year' in df.columns:
                            df['year'] = df['year'].astype(str).str.strip()

                        initial_count = len(df)
                        df = df.drop_duplicates(subset=['entity_name', 'year'], keep='last')
                        deduped_count = len(df)

                        df = df.replace([np.inf, -np.inf], None)
                        df = df.astype(object).where(pd.notnull(df), None)
                        records = df.to_dict(orient='records')

                        if overwrite_unlisted:
                            supabase.table('unlisted_register').delete().neq('id', 0).execute()

                        supabase.table('unlisted_register').insert(records).execute()
                        st.cache_data.clear()
                        
                        removed_dupes = initial_count - deduped_count
                        st.success(f"✅ Successfully synced {deduped_count} Unlisted Entity records! ({removed_dupes} duplicates removed)")
                    except Exception as e:
                        st.error(f"Sync failed: {e}")

    # --- ADMIN TAB 2: PDF UPLOADER ---
    with admin_tab2:
        if "uploader_key" not in st.session_state:
            st.session_state.uploader_key = 0

        col_upload, col_reset = st.columns([5, 1])
        with col_upload:
            uploaded_files = st.file_uploader(
                "Select PDF reports", 
                type=['pdf'], 
                accept_multiple_files=True,
                key=f"pdf_uploader_{st.session_state.uploader_key}"
            )

        with col_reset:
            st.write("")
            st.write("")
            if st.button("🔄 Clear Files", use_container_width=True):
                st.session_state.uploader_key += 1
                st.rerun()

        submit_btn = st.button("⚡ Process & Index Batch", type="primary", use_container_width=True)

        if submit_btn and uploaded_files:
            if not api_key:
                st.error("🔑 API Key missing from configuration (`st.secrets`). Please verify settings.")
            elif not supabase or (not db and not cred_dict):
                st.error("⚠️ Database/Storage connections missing.")
            else:
                client = genai.Client(api_key=api_key)
                active_models = ["gemini-2.5-flash", "gemini-1.5-flash"]
                progress = st.progress(0)
                
                for idx, file in enumerate(uploaded_files):
                    st.info(f"Processing [{idx+1}/{len(uploaded_files)}]: {file.name}...")
                    raw_bytes = file.getvalue()
                    tmp_path = None

                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(raw_bytes)
                            tmp_path = tmp.name

                        # Extract PDF raw text for full-text search indexing
                        extracted_text = extract_pdf_content(tmp_path)

                        g_file = client.files.upload(file=tmp_path, config={"mime_type": "application/pdf"})
                        prompt = """
                        Analyze the internal text of this audit report carefully and extract details into JSON:
                        {
                            "display_title": "Full Formal Display Title of Report",
                            "platform_name": "Primary Platform Name",
                            "document_type": "GS007 Report, SOC 1 Report, SOC 3 Report, or Bridge Letter",
                            "date_coverage_period": "e.g. 1 July 2022 - 30 June 2023",
                            "financial_year": "Original report year e.g. FY2023",
                            "aus_financial_year": "Corresponding Australian Financial Year e.g. FY2023",
                            "doc_role": "Role e.g., 'Primary Control Report'",
                            "auditing_firm": "Auditor Name",
                            "audit_opinion": "Unqualified or Qualified",
                            "key_exceptions_summary": "Summary of exceptions or 'None flagged'"
                        }
                        """
                        res = None
                        for m_name in active_models:
                            try:
                                res = client.models.generate_content(
                                    model=m_name, contents=[g_file, prompt],
                                    config={"response_mime_type": "application/json", "temperature": 0.1}
                                )
                                if res and res.text:
                                    break
                            except Exception:
                                continue

                        if res and res.text:
                            metadata = robust_json_decode(res.text) or {}
                            safe_filename = file.name.replace(" ", "_")
                            s_path = f"reports/{safe_filename}"
                            
                            # Upload to Supabase Bucket
                            supabase.storage.from_("pdfs").upload(
                                s_path, raw_bytes, {"content-type": "application/pdf", "x-upsert": "true"}
                            )
                            pub_url = supabase.storage.from_("pdfs").get_public_url(s_path)
                            
                            # Construct dual viewing/downloading action links
                            metadata["source_filename"] = file.name
                            metadata["original_filename"] = file.name
                            metadata["extracted_content"] = extracted_text
                            metadata["download_url"] = f"{pub_url}?download=true"
                            metadata["view_url"] = pub_url
                            metadata["created_at"] = time.time()
                            
                            save_report_metadata(metadata)
                            st.success(f"Indexed: `{file.name}` -> **{metadata.get('platform_name', file.name)}**")
                    except Exception as e:
                        st.error(f"Error handling {file.name}: {e}")
                    finally:
                        if tmp_path and os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    progress.progress((idx + 1) / len(uploaded_files))

                st.cache_data.clear()
                st.success("Batch processing complete!")
