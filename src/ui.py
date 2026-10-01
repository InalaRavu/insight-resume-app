import base64
import os
from pathlib import Path

import httpx
import streamlit as st

from src import config  # noqa: F401 - loads .env before the constants below
from src.auth import AuthError, principal_from_headers

# The backend listens on container loopback only; it is never exposed publicly.
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("UI_REQUEST_TIMEOUT", "180"))

st.set_page_config(
    page_title="NEXA | Resume Builder",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)


# Helper to encode local image for clean inline HTML rendering
def get_image_base64(path_str: str) -> str:
    path = Path(__file__).resolve().parent.parent / path_str
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
    .dev-pill {
        background: rgba(255, 193, 7, 0.95);
        color: #3A2A00;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.3px;
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


# =========================================================================
# AUTHENTICATION GATE (Microsoft Entra ID via Azure App Service Easy Auth)
#
# Easy Auth validates the token at the platform edge and injects the verified
# principal as request headers. If no principal is present the user is not
# signed in, and the application renders nothing but a sign-in prompt.
# =========================================================================
def _request_headers() -> dict:
    try:
        return dict(st.context.headers)
    except Exception:  # noqa: BLE001 - older Streamlit, or no active request
        return {}


def _render_sign_in_screen(message: str) -> None:
    st.markdown(f"""
    <div class="nexa-topbar">
        <div class="brand-container">
            <div style="background:#FFF; padding:10px; border-radius:4px; display:inline-block;">
                <span style="color:#000; font-weight:600; font-size:1.4rem;">NEXA
                <small style="color:#E6007E;">BUILDER</small></span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.error(message)
    st.markdown(
        '<a href="/.auth/login/aad?post_login_redirect_uri=/" '
        'style="display:inline-block; background:linear-gradient(90deg,#E6007E,#5C2483); '
        'color:#FFF; padding:12px 28px; border-radius:8px; text-decoration:none; '
        'font-weight:600;">Sign in with Microsoft</a>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Access is restricted to Insight corporate accounts. For local development, "
        "set ALLOW_ANONYMOUS_AUTH=true in your .env file."
    )


incoming_headers = _request_headers()
try:
    principal = principal_from_headers(incoming_headers)
except AuthError as exc:
    _render_sign_in_screen(str(exc))
    st.stop()


def backend_headers() -> dict:
    """Forward the verified principal to the backend.

    The backend trusts these headers because it binds to container loopback and
    is unreachable from outside; see the deployment note in the README.
    """
    forwarded = {
        k: v for k, v in incoming_headers.items()
        if k.lower().startswith("x-ms-client-principal")
    }
    if not forwarded and principal.is_dev_identity:
        forwarded["X-Ms-Client-Principal-Name"] = principal.email
    return forwarded


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

dev_badge = '<div class="dev-pill">DEV IDENTITY</div>' if principal.is_dev_identity else ""

st.markdown(f"""
<div class="nexa-topbar">
    <div class="brand-container">
        {logo_html}
    </div>
    <div class="user-actions">
        {dev_badge}
        <a href="#help" class="help-link">❓ Help</a>
        <div class="user-pill">👤 {principal.email}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# State Management
if "active_nav" not in st.session_state:
    st.session_state.active_nav = "Upgrade your resume"
if "manual_section" not in st.session_state:
    st.session_state.manual_section = "Personal Info"
if "standardized_bytes" not in st.session_state:
    st.session_state.standardized_bytes = None
if "resume_filename" not in st.session_state:
    st.session_state.resume_filename = ""

# 3-Pane Responsive Layout
left_col, center_col, right_col = st.columns([1.1, 2.2, 1.2], gap="medium")

# =========================================================================
# PANE 1: Navigation & Fill Section
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
                    icon2, label2 = sections[i + 1]
                    with c2:
                        is_active2 = (st.session_state.manual_section == label2)
                        if st.button(f"{icon2}\n{label2}", key=f"btn_{label2}", use_container_width=True,
                                     type="primary" if is_active2 else "secondary"):
                            st.session_state.manual_section = label2
                            st.rerun()

# =========================================================================
# PANE 2: Upload Resume OR Form Workspace
# =========================================================================
with center_col:
    with st.container(border=True):
        if st.session_state.active_nav == "Upgrade your resume":
            st.markdown("""
                <h3 style="margin-top:0; color:#1F2937; font-weight:700;">Upgrade Your Existing Resume</h3>
                <p style="color:#6B7280; font-size:0.92rem; margin-bottom:20px;">Upload an existing document to synthesize, re-index, and align it to corporate branding.</p>
            """, unsafe_allow_html=True)

            uploaded_file = st.file_uploader(
                "Upload Document",
                type=["docx", "pdf"],
                label_visibility="collapsed"
            )
            st.caption(
                "Accepts .docx and text-based .pdf. Legacy .doc files must be re-saved as "
                ".docx in Word first. Scanned/image-only PDFs cannot be read."
            )

            st.write("")
            upgrade_btn = st.button("⚡ Upgrade Resume", type="primary", disabled=uploaded_file is None)

            if upgrade_btn and uploaded_file is not None:
                # The HuggingFace free tier regularly takes 60-120s for a full
                # resume, so the wait is set out explicitly rather than left to
                # a bare spinner that looks indistinguishable from a hang.
                with st.spinner(
                    "Extracting entities and aligning corporate templates... "
                    "This usually takes 1-2 minutes on the free AI tier."
                ):
                    try:
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                        response = httpx.post(
                            f"{BACKEND_URL}/standardize-resume",
                            files=files,
                            headers=backend_headers(),
                            timeout=REQUEST_TIMEOUT,
                        )

                        if response.status_code == 200:
                            st.session_state.standardized_bytes = response.content
                            st.session_state.resume_filename = f"Standardized_{Path(uploaded_file.name).stem}.docx"
                            st.rerun()
                        else:
                            # The backend returns actionable messages in `detail`.
                            try:
                                detail = response.json().get("detail", response.text)
                            except Exception:  # noqa: BLE001
                                detail = response.text
                            st.error(f"Could not process this resume: {detail}")
                    except httpx.TimeoutException:
                        st.error(
                            "The extraction service timed out. Very long resumes can exceed the "
                            "time limit -- please retry."
                        )
                    except httpx.RequestError as exc:
                        st.error(
                            f"Cannot reach the backend at {BACKEND_URL}. Make sure the FastAPI "
                            f"service is running. ({exc})"
                        )

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

            st.warning(
                "**Preview only.** This section is not wired to the document engine yet -- "
                "entries are not saved and cannot be compiled. Date pickers for each company "
                "and project, plus skill and certification pickers, are the next milestone. "
                "Use **Upgrade your resume** for a working end-to-end document today.",
                icon="🚧",
            )

            if st.session_state.manual_section == "Personal Info":
                st.text_input("Full Name", placeholder="e.g. Jane Doe", key="pi_name")
                col_r, col_l = st.columns(2)
                with col_r:
                    st.text_input("Target Designation", placeholder="e.g. Architect - Data & AI", key="pi_title")
                with col_l:
                    st.text_input("Location / City", placeholder="e.g. Gurugram, India", key="pi_location")

            elif st.session_state.manual_section == "Exec Summary":
                st.text_area("Executive Summary", placeholder="Enter structured executive profile overview...",
                             height=200, key="es_summary")

            elif st.session_state.manual_section == "Work Experience":
                st.text_input("Company / Organization", placeholder="e.g. Insight Direct India Pvt. Ltd.", key="we_company")
                col_t, col_d = st.columns(2)
                with col_t:
                    st.text_input("Role Title", placeholder="e.g. Lead Architect", key="we_role")
                with col_d:
                    st.text_input("Duration", placeholder="e.g. Apr 2012 - Present", key="we_duration")
                st.text_area("Key Responsibilities & Deliverables", placeholder="• Bullet 1\n• Bullet 2",
                             height=150, key="we_bullets")

            elif st.session_state.manual_section == "Education":
                st.text_input("Institution Name", placeholder="e.g. Delhi University", key="ed_institution")
                col_deg, col_yr = st.columns(2)
                with col_deg:
                    st.text_input("Degree / Major", placeholder="e.g. B.Tech Computer Science", key="ed_degree")
                with col_yr:
                    st.text_input("Year of Completion", placeholder="e.g. 2012", key="ed_year")

            elif st.session_state.manual_section == "Areas of Expertise":
                st.text_area("Technical & Functional Domains",
                             placeholder="e.g. Solution Architecture, Enterprise Data Warehousing, GenAI Integrations",
                             height=150, key="ax_areas")

            elif st.session_state.manual_section == "Certifications":
                st.text_area("Official Credentials",
                             placeholder="• Microsoft Certified: Azure Solutions Architect Expert",
                             height=150, key="ce_certs")

            st.write("")
            btn_c1, btn_c2 = st.columns([1, 1])
            with btn_c1:
                st.button("Save Section", type="primary", use_container_width=True, disabled=True)
            with btn_c2:
                st.button("Reset Form", type="secondary", use_container_width=True, disabled=True)

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
            st.success("Resume standardization complete.")
            st.markdown(f"**File:** `{st.session_state.resume_filename}`")

            st.download_button(
                label="📥 Download Resume (.docx)",
                data=st.session_state.standardized_bytes,
                file_name=st.session_state.resume_filename,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True
            )
            if st.button("Start over", type="secondary", use_container_width=True):
                st.session_state.standardized_bytes = None
                st.session_state.resume_filename = ""
                st.rerun()
        else:
            st.info("No document compiled yet. Upload a resume to activate download.")

        st.markdown("""
            <div class="ai-disclaimer">
                <strong>Responsible AI Notice:</strong><br/>
                Content is extracted and structured using generative AI. Verify dates, credentials, and achievements for fidelity prior to client distribution.
            </div>
        """, unsafe_allow_html=True)
