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

# Premium Enterprise Theme Inspired by Modern SaaS Workspace
st.markdown("""
<style>
    /* Global Canvas Styling */
    .stApp {
        background-color: #F1F3F8 !important;
        color: #1F2937 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }
    
    /* Remove default streamlit header margins */
    /* 1. Hide default Streamlit top header bar that blocks the top elements */
    header[data-testid="stHeader"] {
        display: none !important;
    }

    /* 2. Set exact 10pt spacing at the very top of the window */
    .block-container {
        padding-top: 10pt !important;
        padding-bottom: 2rem !important;
        max-width: 96% !important;
    }

    /* 3. Top Vibrant Enterprise App Bar */
    .nexa-topbar {
        background: linear-gradient(135deg, #4A197D 0%, #68228B 50%, #B8006E 100%);
        padding: 10px 24px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-radius: 12px;
        margin-bottom: 22px;
        box-shadow: 0 8px 24px -4px rgba(74, 25, 125, 0.35);
        min-height: 72px; /* Ensures ample room so nothing gets cut off */
    }

    /* Logo badge container - fits dark logo seamlessly without clipping */
    .logo-badge {
        background: #000000;
        border: 1px solid rgba(255, 255, 255, 0.15);
        padding: 6px 14px;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .brand-container {
        display: flex;
        align-items: center;
        gap: 16px;
    }
    .logo-badge {
        background: #FFFFFF;
        padding: 4px 14px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.12);
        display: flex;
        align-items: center;
    }
    .user-actions {
        display: flex;
        align-items: center;
        gap: 24px;
    }
    .help-anchor {
        color: #FDE8F3 !important;
        text-decoration: none !important;
        font-size: 0.92rem;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 6px;
        transition: opacity 0.2s;
    }
    .help-anchor:hover {
        opacity: 0.85;
    }
    .user-profile-badge {
        background: rgba(255, 255, 255, 0.16);
        border: 1px solid rgba(255, 255, 255, 0.28);
        backdrop-filter: blur(10px);
        padding: 6px 16px;
        border-radius: 20px;
        color: #FFFFFF;
        font-size: 0.88rem;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    /* Cards / Surfaces */
    .saas-card {
        background: #FFFFFF;
        border-radius: 12px;
        padding: 24px;
        border: 1px solid #E5E7EB;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
        margin-bottom: 20px;
    }
    
    /* Nav Buttons on the Left Panel */
    div.stButton > button[data-testid="baseButton-primary"] {
        background: linear-gradient(90deg, #E6007E 0%, #5C2483 100%) !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 14px rgba(230, 0, 126, 0.3) !important;
    }
    div.stButton > button[data-testid="baseButton-secondary"] {
        background: #FFFFFF !important;
        color: #374151 !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
    }
    div.stButton > button[data-testid="baseButton-secondary"]:hover {
        border-color: #5C2483 !important;
        color: #5C2483 !important;
        background: #FAF7FD !important;
    }

    /* File Uploader Custom Styling */
    div[data-testid="stFileUploader"] {
        background: #FFFFFF;
        border: 2px dashed #D1D5DB;
        border-radius: 10px;
        padding: 16px;
    }

    /* AI Governance Notice */
    .ai-disclaimer {
        background: #FDF4F9;
        border-left: 4px solid #E6007E;
        padding: 14px 18px;
        border-radius: 6px;
        font-size: 0.84rem;
        color: #4A197D;
        line-height: 1.5;
        margin-top: 18px;
    }
</style>
""", unsafe_allow_html=True)

# 1. User Principal
headers = getattr(st, "context", {}).headers if hasattr(st, "context") else {}
user_email = headers.get("X-Ms-Client-Principal-Name", "ravi.shankar@insight.com")

# 2. Top App Bar (NEXA Illuminated Banner)
logo_img_html = (
    f'<img src="data:image/png;base64,{nexa_b64}" height="42" style="display:block; object-fit:contain;" />'
    if nexa_b64 else 
    '<span style="color:#5C2483; font-weight:900; font-size:1.3rem;">NEXA <small style="color:#E6007E;">BUILDER</small></span>'
)

topbar_html = f"""
<div class="nexa-topbar">
    <div class="brand-container">
        <div class="logo-badge">
            {logo_img_html}
        </div>
    </div>
    <div class="user-actions">
        <a href="#help" class="help-anchor">❓ Help</a>
        <div class="user-profile-badge">
            <span>👤</span>
            <span>{user_email}</span>
        </div>
    </div>
</div>
"""
st.markdown(topbar_html, unsafe_allow_html=True)

# 3. State Management
if "active_nav" not in st.session_state:
    st.session_state.active_nav = "Upgrade your resume"
if "manual_section" not in st.session_state:
    st.session_state.manual_section = "Personal Info"
if "standardized_bytes" not in st.session_state:
    st.session_state.standardized_bytes = None
if "resume_filename" not in st.session_state:
    st.session_state.resume_filename = ""

# 4. Global App Layout: Left Sidebar Controls & Right Workspace Canvas
nav_col, content_col = st.columns([1, 4.2], gap="large")

with nav_col:
    # Left Navigation Actions (Clean Buttons without 'Navigation' header)
    if st.button("⚡  Upgrade your resume", use_container_width=True, 
                 type="primary" if st.session_state.active_nav == "Upgrade your resume" else "secondary"):
        st.session_state.active_nav = "Upgrade your resume"
        st.rerun()

    if st.button("📝  Create your Resume", use_container_width=True, 
                 type="primary" if st.session_state.active_nav == "Create your Resume" else "secondary"):
        st.session_state.active_nav = "Create your Resume"
        st.rerun()

    st.write("")
    st.markdown("<hr style='border: none; border-top: 1px solid #E2E8F0; margin: 15px 0;'/>", unsafe_allow_html=True)
    st.caption("Insight Digital Innovation • Enterprise GenAI Platform")

with content_col:
    # ================= VIEW 1: UPGRADE YOUR RESUME =================
    if st.session_state.active_nav == "Upgrade your resume":
        st.markdown("""
        <div class="saas-card">
            <h3 style="margin-top:0; color:#1F2937; font-weight:700;">Upgrade Your Existing Resume</h3>
            <p style="color:#6B7280; font-size:0.95rem;">Upload an existing document (.doc, .docx, .pdf) to synthesize, re-index, and align it to corporate branding.</p>
        </div>
        """, unsafe_allow_html=True)

        with st.container():
            uploaded_file = st.file_uploader(
                "Upload Resume Document",
                type=["doc", "docx", "pdf"],
                help="Supports DOCX and PDF formats up to 200MB."
            )

            st.write("")
            upgrade_btn = st.button("⚡ Upgrade Resume", type="primary", disabled=uploaded_file is None)

            if upgrade_btn and uploaded_file is not None:
                with st.spinner("Extracting entities and generating standardized document..."):
                    try:
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                        response = httpx.post("http://127.0.0.1:8000/standardize-resume", files=files, timeout=120.0)

                        if response.status_code == 200:
                            st.session_state.standardized_bytes = response.content
                            st.session_state.resume_filename = f"Standardized_{Path(uploaded_file.name).stem}.docx"
                            st.success("Resume successfully standardized!")
                        else:
                            st.error(f"Processing failed: {response.text}")
                    except Exception as e:
                        st.error(f"Backend communication error: {str(e)}")

            if st.session_state.standardized_bytes:
                st.write("")
                st.markdown(f"""
                <div class="saas-card" style="border-left: 4px solid #5C2483;">
                    <h4 style="margin-top:0; color:#1F2937;">Resume Ready for Download</h4>
                    <p style="color:#4B5563; font-size:0.9rem;"><strong>File:</strong> <code>{st.session_state.resume_filename}</code></p>
                </div>
                """, unsafe_allow_html=True)

                st.download_button(
                    label="📥 Download Standardized Resume (.docx)",
                    data=st.session_state.standardized_bytes,
                    file_name=st.session_state.resume_filename,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="primary"
                )

                st.markdown("""
                <div class="ai-disclaimer">
                    <strong>Responsible AI &amp; Enterprise Governance Notice:</strong><br/>
                    This resume has been synthesized and structured using enterprise Generative AI adhering to corporate formatting guidelines.
                    Please verify all candidate timelines, metrics, and technical skills before sharing with prospective clients.
                </div>
                """, unsafe_allow_html=True)

    # ================= VIEW 2: CREATE YOUR RESUME (MATCHING 3-PANE WORKSPACE) =================
    elif st.session_state.active_nav == "Create your Resume":
        # 3-Pane Structure from Reference Image: [Section Grid] | [Form Inputs] | [Preview/Settings]
        pane_sections, pane_form, pane_actions = st.columns([1.2, 2.2, 1.2], gap="medium")

        # --- PANE 1: Section Tiles ---
        with pane_sections:
            st.markdown("""
            <div style="font-weight:700; color:#1F2937; margin-bottom:4px;">Fill Section</div>
            <div style="font-size:0.8rem; color:#6B7280; margin-bottom:14px;">Select a section to populate details.</div>
            """, unsafe_allow_html=True)

            sections = [
                ("👤", "Personal Info"),
                ("📝", "Summary"),
                ("💼", "Work Experience"),
                ("📖", "Education"),
                ("🌐", "Language"),
                ("🎖️", "Areas of Expertise"),
                ("🎓", "Courses"),
                ("💻", "Computer Skills"),
            ]

            # 2-column grid of tiles
            for i in range(0, len(sections), 2):
                c1, c2 = st.columns(2)
                icon1, label1 = sections[i]
                with c1:
                    is_active1 = st.session_state.manual_section == label1
                    if st.button(f"{icon1}\n{label1}", key=f"sec_{label1}", use_container_width=True,
                                 type="primary" if is_active1 else "secondary"):
                        st.session_state.manual_section = label1
                        st.rerun()

                if i + 1 < len(sections):
                    icon2, label2 = sections[i+1]
                    with c2:
                        is_active2 = st.session_state.manual_section == label2
                        if st.button(f"{icon2}\n{label2}", key=f"sec_{label2}", use_container_width=True,
                                     type="primary" if is_active2 else "secondary"):
                            st.session_state.manual_section = label2
                            st.rerun()

            st.write("")
            st.button("➕ New Section", use_container_width=True, type="secondary")

        # --- PANE 2: Form Editor ---
        with pane_form:
            st.markdown(f"""
            <div class="saas-card" style="margin-bottom:12px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <h4 style="margin:0; color:#1F2937;">{st.session_state.manual_section}</h4>
                        <span style="font-size:0.8rem; color:#6B7280;">Fill in official candidate qualifications and accomplishments</span>
                    </div>
                    <span style="font-size:1.1rem; color:#6B7280;">✏️</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            with st.container(border=True):
                if st.session_state.manual_section == "Personal Info":
                    st.text_input("Full Name", placeholder="e.g. Ravi Shankar Inala")
                    c_role, c_loc = st.columns(2)
                    with c_role:
                        st.text_input("Target Role / Title", placeholder="e.g. Architect - Data & AI")
                    with c_loc:
                        st.text_input("City / Location", placeholder="e.g. Hyderabad, India")

                elif st.session_state.manual_section == "Summary":
                    st.text_area("Executive Summary", placeholder="Write a high-impact professional overview...", height=180)

                elif st.session_state.manual_section == "Work Experience":
                    st.text_input("Organization / Client", placeholder="e.g. Insight Direct India Pvt. Ltd.")
                    c_title, c_dates = st.columns(2)
                    with c_title:
                        st.text_input("Role Title", placeholder="e.g. Senior Architect")
                    with c_dates:
                        st.text_input("Tenure", placeholder="e.g. 2021 - Present")
                    st.text_area("Key Responsibilities & Impact", placeholder="• Point 1\n• Point 2", height=140)

                elif st.session_state.manual_section == "Education":
                    st.text_input("Institution Name", placeholder="e.g. JNTU")
                    st.text_input("Degree / Major", placeholder="e.g. B.Tech in Computer Science")
                    st.text_input("Year of Completion", placeholder="e.g. 2012")

                else:
                    st.text_area(f"Content for {st.session_state.manual_section}", placeholder=f"Provide detailed bullet points for {st.session_state.manual_section}...", height=160)

                st.write("")
                f_save, f_clear = st.columns([1, 1])
                with f_save:
                    st.button("Save Section", type="primary", use_container_width=True)
                with f_clear:
                    st.button("Reset Form", type="secondary", use_container_width=True)

        # --- PANE 3: Actions & Output Settings ---
        with pane_actions:
            st.markdown("""
            <div style="font-weight:700; color:#1F2937; margin-bottom:4px;">Resume Settings</div>
            <div style="font-size:0.8rem; color:#6B7280; margin-bottom:14px;">Branded corporate template</div>
            """, unsafe_allow_html=True)

            with st.container(border=True):
                st.markdown("**Active Template:** `Corporate ATS v1`")
                st.caption("Standardized margins, compliant tables, and ampersand safety enabled.")
                st.write("")
                st.button("👁️ Preview Layout", use_container_width=True, type="secondary")
                st.write("")
                st.button("🚀 Compile Word Document", type="primary", use_container_width=True)