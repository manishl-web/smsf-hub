import os
import json
import re
import time
import tempfile
import streamlit as st
import pandas as pd
import google.cloud.firestore as firestore
from google import genai
from supabase import create_client

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
    .hero-banner { background: linear-gradient(135deg, #0F172A 0%, #1E293B 50%, #1E40AF 100%); padding: 2.2rem 2rem; border-radius: 20px; color: white; margin-bottom: 1.5rem; }
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

@st.cache_resource
def init_services():
    db = None
    if "gcp_service_account" in st.secrets and "textkey" in st.secrets["gcp_service_account"]:
        try:
            cred_dict = json.loads(st.secrets["gcp_service_account"]["textkey"])
            db = firestore.Client.from_service_account_info(cred_dict)
        except Exception as e:
            st.sidebar.error(f"Firestore Auth Error: {e}")

    supabase = None
    sb_url = st.secrets.get("SUPABASE_URL", "")
    sb_key = st.secrets.get("SUPABASE_KEY", "")
    if sb_url and sb_key:
        try:
            supabase = create_client(sb_url, sb_key)
        except Exception as e:
            st.sidebar.error(f"Supabase Auth Error: {e}")

    return db, supabase

db, supabase = init_services()

if db:
    st.sidebar.markdown('🌐 <span style="color:#166534; font-weight:700;">Firestore Connected</span>', unsafe_allow_html=True)
else:
    st.sidebar.warning("⚠️ Firestore Offline")

if supabase:
    st.sidebar.markdown('⚡ <span style="color:#166534; font-weight:700;">Supabase Storage Connected</span>', unsafe_allow_html=True)
else:
    st.sidebar.warning("⚠️ Supabase Offline")

@st.cache_data(ttl=300)
def fetch_reports():
    if not db:
        return []
    docs = list(db.collection('type2_reports').stream())
    return [d.to_dict() for d in docs]

st.sidebar.title("🛡️ Audit Portal")
app_mode = st.sidebar.radio("Navigate", ["🔍 Search & Analytics Hub", "📤 AI Batch Upload Studio"])
api_key = st.sidebar.text_input("Gemini API Key", type="password", value=st.secrets.get("GEMINI_API_KEY", ""))

if app_mode == "🔍 Search & Analytics Hub":
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
    fcol1, fcol2, fcol3 = st.columns([2, 1, 1])
    with fcol1:
        q = st.text_input("🔍 Keyword Search (Platform, Auditor, Exceptions)", "").strip().lower()
    with fcol2:
        fy_options = ["All Years"] + [f"FY{year}" for year in range(2021, 2031)]
        fy_sel = st.selectbox("Financial Year", fy_options)
    with fcol3:
        status_sel = st.selectbox("Audit Status Filter", ["All Reports", "Qualified Only", "Unqualified Only"])

    st.divider()

    # Filter reports
    filtered = []
    for r in reports:
        search_blob = f"{r.get('platform_name', '')} {r.get('auditing_firm', '')} {r.get('audit_opinion', '')} {r.get('key_exceptions_summary', '')}".lower()
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

    # Group reports by Platform Name and AU FY to put staggered reports under one roof
    grouped_reports = {}
    for r in filtered:
        group_key = f"{r.get('platform_name', 'Unknown Platform')} - {r.get('aus_financial_year', r.get('financial_year', 'FY2025'))}"
        if group_key not in grouped_reports:
            grouped_reports[group_key] = []
        grouped_reports[group_key].append(r)

    st.markdown(f"Showing **{len(grouped_reports)}** Compliance Packages ({len(filtered)} documents total):")

    for group_key, doc_list in grouped_reports.items():
        primary_doc = doc_list[0]
        platform_name = primary_doc.get('platform_name', 'Unknown Platform')
        aus_fy = primary_doc.get('aus_financial_year', primary_doc.get('financial_year', 'FY2025'))
        
        # Determine overall opinion
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
        
        # Render each associated sub-document inside the unified card
        for d in doc_list:
            role_tag = f"<b>[{d.get('doc_role', 'Control Report')}]</b> " if d.get('doc_role') else ""
            date_range = f" ({d.get('date_coverage_period', '')})" if d.get('date_coverage_period') else ""
            
            col_left, col_right = st.columns([4, 1])
            with col_left:
                st.markdown(f"""
                <div class="sub-doc-pill">
                    📄 {role_tag}<strong>{d.get('source_filename', 'Report.pdf')}</strong>{date_range}<br/>
                    <span style="color:#475569;">Exceptions: {d.get('key_exceptions_summary', 'None flagged')}</span>
                </div>
                """, unsafe_allow_html=True)
            with col_right:
                if d.get('download_url'):
                    st.link_button("📥 Download", d['download_url'])
        
        st.markdown("</div>", unsafe_allow_html=True)

elif app_mode == "📤 AI Batch Upload Studio":
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">AI Batch Processing Studio</div>
        <div class="hero-subtitle">Parse, extract, and index GS007/SOC1 reports dynamically</div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("🚨 Database Maintenance & Purge Controls"):
        st.warning("Use this control to wipe all database entries and clear storage if starting clean.")
        if st.button("🗑️ Reset Database & Delete All Records"):
            if db:
                docs = list(db.collection('type2_reports').stream())
                for doc in docs:
                    doc.reference.delete()
            if supabase:
                try:
                    files = supabase.storage.from_("pdfs").list("reports")
                    file_names = [f["name"] for f in files if "name" in f]
                    if file_names:
                        supabase.storage.from_("pdfs").remove([f"reports/{fn}" for fn in file_names])
                except Exception as e:
                    st.error(f"Storage reset error: {e}")
            st.cache_data.clear()
            st.success("✅ Database and Storage successfully wiped! You are ready to start fresh.")
            st.rerun()

    with st.form("batch_upload_form"):
        uploaded_files = st.file_uploader("Select PDF reports", type=['pdf'], accept_multiple_files=True)
        submit_btn = st.form_submit_button("⚡ Process & Index Batch")

    if submit_btn and uploaded_files:
        if not api_key:
            st.error("🔑 Please enter your Gemini API Key in the left sidebar.")
        elif not supabase or not db:
            st.error("⚠️ Database/Storage connections missing. Check configuration.")
        else:
            client = genai.Client(api_key=api_key)
            
            active_models = []
            try:
                available = client.models.list()
                for m in available:
                    m_name = m.name.replace("models/", "")
                    if "flash" in m_name or "pro" in m_name:
                        active_models.append(m_name)
            except Exception:
                active_models = ["gemini-3.6-flash", "gemini-1.5-flash"]

            st.caption(f"🤖 Dynamic Model Pool Active: `{', '.join(active_models[:3])}`")
            progress = st.progress(0)
            
            existing_docs = [d.to_dict() for d in db.collection('type2_reports').stream()]
            
            for idx, file in enumerate(uploaded_files):
                st.info(f"Processing [{idx+1}/{len(uploaded_files)}]: {file.name}...")
                
                filename_duplicate = any(d.get("source_filename") == file.name for d in existing_docs)
                if filename_duplicate:
                    st.warning(f"⚠️ **Skipped**: Document with filename `{file.name}` already exists in the database.")
                    progress.progress((idx + 1) / len(uploaded_files))
                    continue

                raw_bytes = file.getvalue()
                tmp_path = None

                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(raw_bytes)
                        tmp_path = tmp.name

                    g_file = client.files.upload(file=tmp_path, config={"mime_type": "application/pdf"})
                    
                    prompt = """
                    Extract details from this audit document in raw valid JSON format:
                    {
                        "platform_name": "Primary Platform Name (e.g. Interactive Brokers, BT Panorama)",
                        "document_type": "GS007 Report, SOC 1 Report, SOC 3 Report, or Bridge Letter",
                        "date_coverage_period": "Exact period tested, e.g., Jan 2024 - Dec 2024 or Jan 2025 - Jun 2025",
                        "financial_year": "Original report year e.g. FY2024 or CY2024",
                        "aus_financial_year": "Corresponding Australian Financial Year (1 July - 30 June) this document supports e.g. FY2024 or FY2025",
                        "doc_role": "Role e.g., 'Primary SOC Report (Part 1)', 'Primary SOC Report (Part 2)', or 'Gap/Bridge Letter'",
                        "auditing_firm": "e.g. PwC, Deloitte, KPMG, EY",
                        "audit_opinion": "Unqualified or Qualified",
                        "key_exceptions_summary": "Summary of exceptions or 'None flagged'"
                    }
                    Return ONLY valid JSON without markdown formatting or code blocks.
                    """
                    
                    res = None
                    last_err = None
                    
                    for m_name in active_models:
                        try:
                            res = client.models.generate_content(model=m_name, contents=[g_file, prompt])
                            if res and res.text:
                                break
                        except Exception as m_err:
                            last_err = m_err
                            if "429" in str(m_err) or "RESOURCE_EXHAUSTED" in str(m_err):
                                time.sleep(5)
                            continue

                    if not res or not res.text:
                        st.error(f"Failed to process {file.name}. Details: {last_err}")
                        continue
                    
                    clean_text = res.text.strip()
                    clean_text = re.sub(r'^```json\s*', '', clean_text, flags=re.MULTILINE)
                    clean_text = re.sub(r'^```\s*', '', clean_text, flags=re.MULTILINE)
                    clean_text = re.sub(r'```$', '', clean_text, flags=re.MULTILINE).strip()
                    
                    match = re.search(r'\{.*\}', clean_text, re.DOTALL)
                    if match:
                        metadata = json.loads(match.group(0))
                        
                        storage_path = f"reports/{file.name}"
                        supabase.storage.from_("pdfs").upload(storage_path, raw_bytes, {"x-upsert": "true"})
                        download_url = supabase.storage.from_("pdfs").get_public_url(storage_path)

                        metadata["download_url"] = download_url
                        metadata["source_filename"] = file.name
                        
                        # Generate unique doc ID incorporating source filename hash to allow multiple sub-documents under same platform/FY
                        file_slug = re.sub(r'[^a-zA-Z0-9]', '_', file.name).strip('_')
                        doc_id = f"doc_{file_slug}"
                        
                        db.collection('type2_reports').document(doc_id).set(metadata)
                        existing_docs.append(metadata)
                        st.success(f"✅ Extracted and Indexed: **{file.name}** ({metadata.get('platform_name')} -> {metadata.get('aus_financial_year')})")
                    else:
                        st.warning(f"Could not parse JSON output for {file.name}")

                except Exception as e:
                    st.error(f"Error processing {file.name}: {e}")
                finally:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                
                time.sleep(2)
                progress.progress((idx + 1) / len(uploaded_files))
            
            st.cache_data.clear()
            st.balloons()
