import os
import json
import re
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
    fy25 = sum(1 for r in reports if '2025' in str(r.get('financial_year', '')) or '25' in str(r.get('financial_year', '')))
    m4.markdown(f'<div class="metric-box"><div class="metric-label">FY2025 Reports</div><div class="metric-value" style="color:#2563EB;">{fy25}</div></div>', unsafe_allow_html=True)

    st.write("")
    fcol1, fcol2 = st.columns([3, 1])
    with fcol1:
        q = st.text_input("🔍 Keyword Search (Platform, Auditor, Exceptions)", "").strip().lower()
    with fcol2:
        fy_options = ["All Years"] + [f"FY{year}" for year in range(2021, 2031)]
        fy_sel = st.selectbox("Financial Year", fy_options)

    st.divider()

    filtered = []
    for r in reports:
        search_blob = f"{r.get('platform_name', '')} {r.get('auditing_firm', '')} {r.get('audit_opinion', '')} {r.get('key_exceptions_summary', '')}".lower()
        matches_search = (q in search_blob) if q else True
        doc_fy = str(r.get('financial_year', '')).upper()
        matches_fy = True if fy_sel == "All Years" else (fy_sel.replace("FY", "") in doc_fy)

        if matches_search and matches_fy:
            filtered.append(r)

    if filtered:
        for idx, r in enumerate(filtered):
            opinion = str(r.get('audit_opinion', 'Unqualified'))
            badge = "badge-unqualified" if "unqualified" in opinion.lower() else "badge-qualified"
            
            st.markdown(f"""
            <div class="glass-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <h3 style="margin:0; color:#0F172A; font-weight:700;">🏢 {r.get('platform_name', 'Unknown Platform')}</h3>
                    <span class="{badge}">{opinion.upper()}</span>
                </div>
                <p style="color:#64748B; font-size:0.88rem; margin: 10px 0;">
                    <strong>Doc Type:</strong> {r.get('document_type', 'GS007')} &nbsp;•&nbsp; 
                    <strong>Auditor:</strong> {r.get('auditing_firm', 'N/A')} &nbsp;•&nbsp;
                    <strong>FY:</strong> {r.get('financial_year', 'N/A')}
                </p>
                <div style="background:#F1F5F9; padding:12px; border-radius:10px; font-size:0.88rem; color:#334155; margin-bottom:12px;">
                    <strong>🔍 Control Exceptions:</strong> {r.get('key_exceptions_summary', 'None flagged.')}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if r.get('download_url'):
                st.link_button(f"📥 Download {r.get('source_filename', 'Report.pdf')}", r['download_url'])

elif app_mode == "📤 AI Batch Upload Studio":
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">AI Batch Processing Studio</div>
        <div class="hero-subtitle">Parse, extract, and index GS007/SOC1 reports using Gemini AI and Supabase Storage</div>
    </div>
    """, unsafe_allow_html=True)

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
            progress = st.progress(0)
            
            for idx, file in enumerate(uploaded_files):
                st.info(f"Processing [{idx+1}/{len(uploaded_files)}]: {file.name}...")
                raw_bytes = file.getvalue()
                
                # 1. Upload direct binary to Supabase Storage CDN
                storage_path = f"reports/{file.name}"
                try:
                    supabase.storage.from_("pdfs").upload(storage_path, raw_bytes, {"x-upsert": "true"})
                    download_url = supabase.storage.from_("pdfs").get_public_url(storage_path)
                except Exception as e:
                    st.error(f"Supabase Storage Upload Error: {e}")
                    continue

                # 2. Extract with Gemini
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(raw_bytes)
                        tmp_path = tmp.name

                    g_file = client.files.upload(file=tmp_path, config={"mime_type": "application/pdf"})
                    
                    prompt = """
                    Extract details from this audit document in raw valid JSON:
                    {
                        "platform_name": "Primary Platform Name",
                        "document_type": "GS007 Report or SOC 1 Report",
                        "financial_year": "e.g. FY2025",
                        "auditing_firm": "e.g. PwC, Deloitte, KPMG, EY",
                        "audit_opinion": "Unqualified or Qualified",
                        "key_exceptions_summary": "Summary of exceptions or 'None flagged'"
                    }
                    Return ONLY valid JSON without markdown formatting.
                    """
                    
                    res = client.models.generate_content(model="gemini-2.5-flash", contents=[g_file, prompt])
                    
                    match = re.search(r'\{.*\}', res.text, re.DOTALL)
                    if match:
                        metadata = json.loads(match.group(0))
                        metadata["download_url"] = download_url
                        metadata["source_filename"] = file.name
                        
                        doc_id = f"{metadata.get('platform_name', 'Doc').replace(' ', '_')}_{metadata.get('financial_year', 'FY25')}"
                        db.collection('type2_reports').document(doc_id).set(metadata)
                        st.success(f"✅ Extracted and Indexed: **{file.name}**")
                    else:
                        st.warning(f"Could not parse JSON output for {file.name}")

                except Exception as e:
                    st.error(f"Error processing {file.name}: {e}")
                finally:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                
                progress.progress((idx + 1) / len(uploaded_files))
            
            st.cache_data.clear()
            st.balloons()
