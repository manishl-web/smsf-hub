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
    
    # Filter Controls
    fcol1, fcol2, fcol3, fcol4 = st.columns([2, 1, 1, 1])
    with fcol1:
        q = st.text_input("🔍 Keyword Search (Platform, Auditor, Exceptions)", "").strip().lower()
    with fcol2:
        fy_options = ["All Years"] + [f"FY{year}" for year in range(2021, 2031)]
        fy_sel = st.selectbox("Financial Year", fy_options)
    with fcol3:
        status_sel = st.selectbox("Audit Status Filter", ["All Reports", "Qualified Only", "Unqualified Only"])
    with fcol4:
        sort_order = st.selectbox("Sort Alphabetically", ["A-Z (Ascending)", "Z-A (Descending)"])

    # Filtering logic
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

    # Group reports by Platform + Financial Year
    grouped_reports = {}
    for r in filtered:
        group_key = f"{r.get('platform_name', 'Unknown Platform')} - {r.get('aus_financial_year', r.get('financial_year', 'FY2025'))}"
        if group_key not in grouped_reports:
            grouped_reports[group_key] = []
        grouped_reports[group_key].append(r)

    # Sort groups alphabetically by Platform Name
    reverse_sort = (sort_order == "Z-A (Descending)")
    sorted_group_keys = sorted(
        grouped_reports.keys(),
        key=lambda x: x.lower(),
        reverse=reverse_sort
    )

    # Alphabetical Letter Quick Filter Bar
    st.write("")
    st.markdown("<b>🔤 Quick Alphabet Filter:</b>", unsafe_allow_html=True)
    letters = ["ALL"] + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    selected_letter = st.radio("A-Z Bar", letters, horizontal=True, label_visibility="collapsed")

    # Filter by selected letter
    if selected_letter != "ALL":
        sorted_group_keys = [
            k for k in sorted_group_keys 
            if k.strip().upper().startswith(selected_letter)
        ]

    st.divider()

    st.markdown(f"Showing **{len(sorted_group_keys)}** Compliance Packages ({len(filtered)} total documents):")

    # Render sorted and categorized cards
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
