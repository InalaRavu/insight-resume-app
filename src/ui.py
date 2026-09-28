import streamlit as st
import httpx
from pathlib import Path
import base64

st.set_page_config(
    page_title="NEXA | Resume Builder",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Helper to encode local image for clean inline HTML rendering
def get_image_base64(path_str: str) -> str:
    path = Path(path_str)
    if path.exists():
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    return ""

nexa_b64 = get_image_base64("src/assets/nexa_logo.png")

# CSS: Native Container Elevation & Seamless Header
st.markdown("""
<style>
    /* 1. Reset Root Canvas */
    header[data-testid="stHeader"] {
        display: none !important;
    }
    .stApp {
        background-color: #F1F3F8 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }
    .block-container {
        padding-top: 14px !important;
        padding-bottom: 2rem !important;
        max-width: 96% !important;
    }

    /* 2. Top Header Bar */
    .nexa-topbar {
        background: linear-gradient(135deg, #4A197D 0%, #68228B 50%, #B8006E 100%);
        padding: 12px 28px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-radius: 12px;
        margin-bottom: 20px;
        box-shadow: 0 8px 20px rgba(74, 25, 125, 0.25);
    }
    .brand-container {
        display: flex;
        align-items: center;
    }
    /* Removes white image background by blending it into the header */
    .brand-logo-img {
        height: 48px;
        object-fit: contain;
        background: transparent !important;
        mix-blend-mode: multiply;
        display: block;
    }
    .user-actions {
        display: flex;
        align-items: center;
        gap: 22px;
    }
    .help-link {
        color: #FCE7F3 !important;
        text-decoration: none !important;
        font-size: 0.95rem;
        font-weight: 500;
    }
    .user-pill {
        background: rgba(255, 255, 255, 0.18);
        border: 1px solid rgba(255, 255, 255, 0.32);
        padding: 6px 18px;
        border-radius: 20px;
        color: #FFFFFF;
        font-size: 0.9rem;
        font-weight: 500;
    }

    /* 3. Three Pop-Out Panes: Style native Streamlit bordered containers */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #FFFFFF !important;
        border-radius: 14px !important;
        border: 1px solid #E2E8F0 !important;
        box-shadow: 0 12px 28px rgba(0, 0, 0, 0.08), 0 4px 10px rgba(0, 0, 0, 0.03) !important;
        padding: 22px !important;
        margin-bottom: 15px !important;
    }

    /* 4. Action Buttons */
    div.stButton > button[data-testid="baseButton-primary"] {
        background: linear-gradient(90deg, #E6007E 0%, #5C2483 100%) !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 12px rgba(230, 0, 126, 0.3) !important;
    }
    div.stButton > button[data-testid="baseButton-primary"]:hover {
        opacity: 0.92;
        transform: translateY(-1px);
    }
    div.stButton > button[data-testid="baseButton-secondary"] {
        background: #FFFFFF !important;
        color: #374151 !important;
        border: 1px solid #D8DCE3 !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
    }
    div.stButton > button[data-testid="baseButton-secondary"]:hover {
        border-color: #5C2483 !important;
        color: #5C2483 !important;
        background: #FAF7FD !important;
    }

    /* 5. Inputs */
    .stTextInput input, .stTextArea textarea {
        background-color: #F8FAFC !important;
        color: #1F2937 !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 8px !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #E6007E !important;
        box-shadow: 0 0 0 1px #E6007E !important;
    }

    /* 6. AI Governance Disclaimer Box */
    .ai-disclaimer {
        background: #FDF4F9;
        border-left: 4px solid #E6007E;
        padding: 12px 14px;
        border-radius: 6px;
        font-size: 0.82rem;
        color: #4A197D;
        line-height: 1.5;
        margin-top: 16px;
    }
</style>
""", unsafe_allow_html=True)

# Auth Principal
headers = getattr(st, "context", {}).headers if hasattr(st, "context") else {}
user_email = headers.get("X-Ms-Client-Principal-Name", "ravi.shankar@insight.com")

# Top Header Bar
logo_html = (
    f'<div style="background-color: #FFFFFF; padding: 10px; display: inline-block; border-radius: 4px;">'
    f'<img src="data:image/png;base64,{nexa_b64}" class="brand-logo-img" />'
    f'</div>'
    if nexa_b64 else 
    '<div style="background-color: #FFFFFF; padding: 10px; display: inline-block; border-radius: 4px;">'
    '<span style="color:#000000; font-weight:600; font-size:1.4rem;">NEXA <small style="color:#E6007E;">BUILDER</small></span>'
    '</div>'
)

st.markdown(f"""
<div class="nexa-topbar">
    <div class="brand-container">
        {logo_html}
    </div>
    <div class="user-actions">
        <a href="#help" class="help-link">❓ Help</a>
        <div class="user-pill">👤 {user_email}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# State Management
if "active_nav" not in st.session_state:
    st.session_state.active_nav = "Create your Resume"
if "manual_section" not in st.session_state:
    st.session_state.manual_section = "Personal Info"
if "standardized_bytes" not in st.session_state:
    st.session_state.standardized_bytes = None
if "resume_filename" not in st.session_state:
    st.session_state.resume_filename = ""

# 3-Pane Responsive Layout
left_col, center_col, right_col = st.columns([1.1, 2.2, 1.2], gap="medium")

# =========================================================================
# PANE 1: Navigation & Fill Section (Updated Sections List)
# =========================================================================
with left_col:
    with st.container(border=True):
        if st.button("⚡ Upgrade your resume", use_container_width=True, 
                     type="primary" if st.session_state.active_nav == "Upgrade your resume" else "secondary"):
            st.session_state.active_nav = "Upgrade your resume"
            st.rerun()

        if st.button("📝 Create your Resume", use_container_width=True, 
                     type="primary" if st.session_state.active_nav == "Create your Resume" else "secondary"):
            st.session_state.active_nav = "Create your Resume"
            st.rerun()

        # Conditionally render Fill Section when "Create your Resume" is active
        if st.session_state.active_nav == "Create your Resume":
            st.markdown("<hr style='border:none; border-top:1px solid #EEF1F6; margin: 16px 0;'>", unsafe_allow_html=True)

            st.markdown("""
                <div style="font-weight:700; font-size:1.05rem; color:#1F2937; margin-bottom:2px;">Fill Section</div>
                <div style="font-size:0.8rem; color:#6B7280; margin-bottom:14px;">Select a section to populate details.</div>
            """, unsafe_allow_html=True)

            sections = [
                ("👤", "Personal Info"),
                ("📝", "Exec Summary"),
                ("💼", "Work Experience"),
                ("📖", "Education"),
                ("🎖️", "Areas of Expertise"),
                ("🎓", "Certifications"),
            ]

            for i in range(0, len(sections), 2):
                c1, c2 = st.columns(2)
                icon1, label1 = sections[i]
                with c1:
                    is_active1 = (st.session_state.manual_section == label1)
                    if st.button(f"{icon1}\n{label1}", key=f"btn_{label1}", use_container_width=True,
                                 type="primary" if is_active1 else "secondary"):
                        st.session_state.manual_section = label1
                        st.rerun()

                if i + 1 < len(sections):
                    icon2, label2 = sections[i+1]
                    with c2:
                        is_active2 = (st.session_state.manual_section == label2)
                        if st.button(f"{icon2}\n{label2}", key=f"btn_{label2}", use_container_width=True,
                                     type="primary" if is_active2 else "secondary"):
                            st.session_state.manual_section = label2
                            st.rerun()

            st.write("")
            st.button("➕ New Section", use_container_width=True, type="secondary")

# =========================================================================
# PANE 2: Upload Resume OR Form Workspace
# =========================================================================
with center_col:
    with st.container(border=True):
        if st.session_state.active_nav == "Upgrade your resume":
            st.markdown("""
                <h3 style="margin-top:0; color:#1F2937; font-weight:700;">Upgrade Your Existing Resume</h3>
                <p style="color:#6B7280; font-size:0.92rem; margin-bottom:20px;">Upload an existing document (.doc, .docx, .pdf) to synthesize, re-index, and align it to corporate branding.</p>
            """, unsafe_allow_html=True)

            uploaded_file = st.file_uploader(
                "Upload Document",
                type=["doc", "docx", "pdf"],
                label_visibility="collapsed"
            )

            st.write("")
            upgrade_btn = st.button("⚡ Upgrade Resume", type="primary", disabled=uploaded_file is None)

            if upgrade_btn and uploaded_file is not None:
                with st.spinner("Extracting entities and aligning corporate templates..."):
                    try:
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                        response = httpx.post("http://127.0.0.1:8000/standardize-resume", files=files, timeout=120.0)

                        if response.status_code == 200:
                            st.session_state.standardized_bytes = response.content
                            st.session_state.resume_filename = f"Standardized_{Path(uploaded_file.name).stem}.docx"
                            st.success("Resume standardization complete.")
                            st.rerun()
                        else:
                            st.error(f"Processing error: {response.text}")
                    except Exception as e:
                        st.error(f"Backend communication error: {str(e)}")

        elif st.session_state.active_nav == "Create your Resume":
            st.markdown(f"""
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                    <div>
                        <h3 style="margin:0; color:#1F2937; font-weight:700;">{st.session_state.manual_section}</h3>
                        <span style="font-size:0.84rem; color:#6B7280;">Fill in candidate credentials and career history</span>
                    </div>
                    <span style="font-size:1.2rem; color:#6B7280;">✏️</span>
                </div>
            """, unsafe_allow_html=True)

            if st.session_state.manual_section == "Personal Info":
                st.text_input("Full Name", placeholder="e.g. Jhon Doe")
                col_r, col_l = st.columns(2)
                with col_r:
                    st.text_input("Target Designation", placeholder="e.g. Architect - Data & AI")
                with col_l:
                    st.text_input("Location / City", placeholder="e.g. Gurugram, India")

            elif st.session_state.manual_section == "Exec Summary":
                st.text_area("Executive Summary", placeholder="Enter structured executive profile overview...", height=200)

            elif st.session_state.manual_section == "Work Experience":
                st.text_input("Company / Organization", placeholder="e.g. Insight Direct India Pvt. Ltd.")
                col_t, col_d = st.columns(2)
                with col_t:
                    st.text_input("Role Title", placeholder="e.g. Lead Architect")
                with col_d:
                    st.text_input("Duration", placeholder="e.g. Apr 2012 - Present")
                st.text_area("Key Responsibilities & Deliverables", placeholder="• Bullet 1\n• Bullet 2", height=150)

            elif st.session_state.manual_section == "Education":
                st.text_input("Institution Name", placeholder="e.g. Delhi University")
                col_deg, col_yr = st.columns(2)
                with col_deg:
                    st.text_input("Degree / Major", placeholder="e.g. B.Tech Computer Science")
                with col_yr:
                    st.text_input("Year of Completion", placeholder="e.g. 2012")

            elif st.session_state.manual_section == "Areas of Expertise":
                st.text_area("Technical & Functional Domains", placeholder="e.g. Solution Architecture, Enterprise Data Warehousing, GenAI Integrations (comma-separated or one per line)", height=150)

            elif st.session_state.manual_section == "Certifications":
                st.text_area("Official Credentials", placeholder="• Microsoft Certified: Azure Solutions Architect Expert\n• Databricks Certified Data Engineer Professional", height=150)

            else:
                st.text_area(f"{st.session_state.manual_section} Items", placeholder=f"Provide detailed bullet items for {st.session_state.manual_section}...", height=180)

            st.write("")
            btn_c1, btn_c2 = st.columns([1, 1])
            with btn_c1:
                st.button("Save Section", type="primary", use_container_width=True)
            with btn_c2:
                st.button("Reset Form", type="secondary", use_container_width=True)

# =========================================================================
# PANE 3: Preview & Download
# =========================================================================
with right_col:
    with st.container(border=True):
        st.markdown("""
            <div style="font-weight:700; font-size:1.05rem; color:#1F2937; margin-bottom:2px;">Export &amp; Preview</div>
            <div style="font-size:0.8rem; color:#6B7280; margin-bottom:16px;">Corporate ATS deliverable</div>
        """, unsafe_allow_html=True)

        if st.session_state.standardized_bytes:
            st.success("Artifact Ready!")
            st.markdown(f"**File:** `{st.session_state.resume_filename}`")
            
            st.download_button(
                label="📥 Download Resume (.docx)",
                data=st.session_state.standardized_bytes,
                file_name=st.session_state.resume_filename,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True
            )
        else:
            st.info("No document compiled yet. Upload or save sections to activate download.")
            st.button("👁️ Preview Resume", use_container_width=True, type="secondary")
            st.write("")
            st.button("🚀 Compile Document", type="primary", use_container_width=True)

        st.markdown("""
            <div class="ai-disclaimer">
                <strong>Responsible AI Notice:</strong><br/>
                Content is extracted and structured using generative AI. Verify dates, credentials, and achievements for fidelity prior to client distribution.
            </div>
        """, unsafe_allow_html=True)