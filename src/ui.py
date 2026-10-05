import base64
from datetime import datetime
import os
from pathlib import Path

import httpx
import streamlit as st

from src import config  # noqa: F401 - loads .env before constants below
from src.auth import AuthError, principal_from_headers

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("UI_REQUEST_TIMEOUT", "180"))

st.set_page_config(
    page_title="NEXA | Resume Builder",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def get_image_base64(path_str: str) -> str:
    path = Path(__file__).resolve().parent.parent / path_str
    if path.exists():
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    return ""


nexa_b64 = get_image_base64("src/assets/nexa_logo.png")

# CSS: 25%-50%-25% Layout, Vertical Button Stack, and Tuned Button Sizing
st.markdown("""
<style>
    /* 1. Root Canvas Reset */
    header[data-testid="stHeader"] {
        display: none !important;
    }
    .stApp {
        background-color: #F1F3F8 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    }
    .block-container {
        padding-top: 14px !important;
        padding-bottom: 8px !important;
        max-width: 98% !important;
    }

    /* 2. Top Header Bar */
    .nexa-topbar {
        background: linear-gradient(135deg, #4A197D 0%, #68228B 50%, #B8006E 100%);
        padding: 10px 24px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-radius: 12px;
        margin-bottom: 14px;
        box-shadow: 0 8px 20px rgba(74, 25, 125, 0.25);
    }
    .brand-container {
        display: flex;
        align-items: center;
    }
    .brand-logo-img {
        height: 42px;
        object-fit: contain;
        background: transparent !important;
        mix-blend-mode: multiply;
        display: block;
    }
    .banner-center-title {
        text-align: center;
        color: #FFFFFF;
        font-size: 1.05rem;
        font-weight: 600;
        letter-spacing: 0.6px;
        white-space: nowrap;
        text-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
    }
    .user-actions {
        display: flex;
        align-items: center;
        gap: 20px;
    }
    .help-link {
        color: #FCE7F3 !important;
        text-decoration: none !important;
        font-size: 0.90rem;
        font-weight: 500;
    }
    .user-pill {
        background: rgba(255, 255, 255, 0.18);
        border: 1px solid rgba(255, 255, 255, 0.32);
        padding: 5px 16px;
        border-radius: 20px;
        color: #FFFFFF;
        font-size: 0.88rem;
        font-weight: 500;
    }
    .dev-pill {
        background: rgba(255, 193, 7, 0.95);
        color: #3A2A00;
        padding: 5px 12px;
        border-radius: 20px;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.3px;
    }

    /* 3. Three Section Cards: Identical Length & Outlines */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #FFFFFF !important;
        border-radius: 16px !important;
        border: 1px solid #E2E8F0 !important;
        box-shadow: 0 12px 28px rgba(0, 0, 0, 0.08), 0 4px 10px rgba(0, 0, 0, 0.03) !important;
        padding: 20px !important;
        height: calc(100vh - 115px) !important;
        min-height: calc(100vh - 115px) !important;
        max-height: calc(100vh - 115px) !important;
        overflow-y: auto !important;
        display: flex !important;
        flex-direction: column !important;
        box-sizing: border-box !important;
        margin-bottom: 0px !important;
    }

    /* 4. Action Buttons & Compact Navigation Sizing */
    div.stButton > button {
        border-radius: 8px !important;
        padding: 7px 12px !important;
        font-size: 0.88rem !important;
        font-weight: 600 !important;
        transition: all 0.15s ease-in-out !important;
    }
    div.stButton > button[data-testid="baseButton-primary"] {
        background: linear-gradient(90deg, #E6007E 0%, #5C2483 100%) !important;
        color: #FFFFFF !important;
        border: none !important;
        box-shadow: 0 3px 10px rgba(230, 0, 126, 0.28) !important;
    }
    div.stButton > button[data-testid="baseButton-primary"]:hover {
        opacity: 0.92;
        transform: translateY(-1px);
    }
    div.stButton > button[data-testid="baseButton-secondary"] {
        background: #FFFFFF !important;
        color: #374151 !important;
        border: 1px solid #D8DCE3 !important;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.02) !important;
    }
    div.stButton > button[data-testid="baseButton-secondary"]:hover {
        border-color: #5C2483 !important;
        color: #5C2483 !important;
        background: #FAF7FD !important;
    }

    /* 5. Inputs & Selectors */
    .stTextInput input, .stTextArea textarea, .stSelectbox [data-baseweb="select"], .stMultiSelect [data-baseweb="select"] {
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
        margin-top: auto;
    }
    
</style>
""", unsafe_allow_html=True)


# =========================================================================
# AUTHENTICATION GATE (Microsoft Entra ID via Azure App Service Easy Auth)
# =========================================================================
def _request_headers() -> dict:
    try:
        return dict(st.context.headers)
    except Exception:
        return {}


def _render_sign_in_screen(message: str) -> None:
    st.markdown("""
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
    forwarded = {
        k: v for k, v in incoming_headers.items()
        if k.lower().startswith("x-ms-client-principal")
    }
    if not forwarded and principal.is_dev_identity:
        forwarded["X-Ms-Client-Principal-Name"] = principal.email
    return forwarded


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
    <div class="banner-center-title">
        NExt generation eXperience &amp; Automation (NEXA)
    </div>
    <div class="user-actions">
        {dev_badge}<a href="#help" class="help-link">❓ Help</a>
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
if "selected_certifications" not in st.session_state:
    st.session_state.selected_certifications = []

if "companies_data" not in st.session_state:
    st.session_state.companies_data = [
        {
            "company": "",
            "role": "",
            "start_month": "Jan",
            "start_year": "2023",
            "end_month": "Dec",
            "end_year": "2026",
            "is_current": True,
            "bullets": "",
        }
    ]

# Curated Industry Certifications Catalog
CERTIFICATION_CATALOG = [
    # Microsoft Azure & Data/AI
    "Microsoft Azure Solutions Architect Expert (AZ-305)",
    "Microsoft DevOps Engineer Expert (AZ-400)",
    "Microsoft Fabric Analytics Engineer Associate (DP-600)",
    "Microsoft Azure Data Engineer Associate (DP-203)",
    "Microsoft Azure AI Engineer Associate (AI-102)",
    "Microsoft Azure Administrator Associate (AZ-104)",
    "Microsoft Azure Developer Associate (AZ-204)",
    "Microsoft Azure Security Engineer Associate (AZ-500)",
    "Microsoft Power BI Data Analyst Associate (PL-300)",
    "Microsoft Azure Fundamentals (AZ-900)",
    "Microsoft Azure AI Fundamentals (AI-900)",
    "Microsoft Azure Data Fundamentals (DP-900)",
    # Databricks
    "Databricks Certified Data Engineer Professional",
    "Databricks Certified Data Engineer Associate",
    "Databricks Certified Machine Learning Professional",
    "Databricks Certified Machine Learning Associate",
    "Databricks Certified Generative AI Engineer Associate",
    # AWS
    "AWS Certified Solutions Architect - Professional (SAP-C02)",
    "AWS Certified Solutions Architect - Associate (SAA-C03)",
    "AWS Certified Data Engineer - Associate (DEA-C01)",
    "AWS Certified DevOps Engineer - Professional (DOP-C02)",
    "AWS Certified Machine Learning - Specialty (MLS-C01)",
    # Google Cloud
    "Google Cloud Professional Cloud Architect",
    "Google Cloud Professional Data Engineer",
    "Google Cloud Professional Cloud Database Engineer",
    "Google Cloud Associate Cloud Engineer",
    # Snowflake & Others
    "Snowflake SnowPro Core Certified (COF-C02)",
    "Snowflake SnowPro Advanced: Architect (ARA-C01)",
    "Snowflake SnowPro Advanced: Data Engineer (DEA-C01)",
    "HashiCorp Certified: Terraform Associate (003)",
    "CKA: Certified Kubernetes Administrator",
    "CKAD: Certified Kubernetes Application Developer",
    "TOGAF 9 / 10 Enterprise Architecture Certified",
    "PMI Project Management Professional (PMP)",
    "Claude Certified Architect: Foundations (CCAR-F)",
    "Claude Certified Developer: Foundations (CCDV-F)", 
    "Claude Certified Associate: Foundations (CCAO-F)",
    "Claude Certified Architect: Professional (CCAR-P)",
]

# Section Subtitle Map
SECTION_SUBTITLES = {
    "Personal Info": "Provide your personal details",
    "Exec Summary": "Enter your significant career achievements. One in each line",
    "Work Experience": "Provide your work experience in reverse chronology - most recent/current as Company #1",
    "Education": "Provide your highest education details only",
    "Areas of Expertise": "Provide your expertise",
    "Certifications": "Provide Professional Certification details",
}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CURRENT_YEAR = datetime.now().year
YEARS = [str(y) for y in range(CURRENT_YEAR + 1, 1990, -1)]

# 25% - 50% - 25% Proportions (1:2:1)
left_col, center_col, right_col = st.columns([1.0, 2.0, 1.0], gap="medium")

# =========================================================================
# PANE 1: Navigation & Fill Section (25% Width)
# =========================================================================
with left_col:
    with st.container(border=True):
        if st.button("⚡ Upgrade your resume", use_container_width=True,
                     type="primary" if st.session_state.active_nav == "Upgrade your resume" else "secondary"):
            st.session_state.active_nav = "Upgrade your resume"
            st.rerun()

        st.write("")
        if st.button("📝 Create your Resume", use_container_width=True,
                     type="primary" if st.session_state.active_nav == "Create your Resume" else "secondary"):
            st.session_state.active_nav = "Create your Resume"
            st.rerun()

        # Fill Section - 1 x 6 Vertical Stack
        if st.session_state.active_nav == "Create your Resume":
            st.markdown("<hr style='border:none; border-top:1px solid #EEF1F6; margin: 14px 0 10px 0;'>", unsafe_allow_html=True)

            st.markdown("""
                <div style="font-weight:700; font-size:0.96rem; color:#1F2937; margin-bottom:1px;">Fill Section</div>
                <div style="font-size:0.78rem; color:#6B7280; margin-bottom:10px;">Select section to edit details:</div>
            """, unsafe_allow_html=True)

            sections = [
                ("👤", "Personal Info"),
                ("📝", "Exec Summary"),
                ("💼", "Work Experience"),
                ("📖", "Education"),
                ("🎖️", "Areas of Expertise"),
                ("🎓", "Certifications"),
            ]

            for icon, label in sections:
                is_active = (st.session_state.manual_section == label)
                if st.button(f"{icon}  {label}", key=f"btn_{label}", use_container_width=True,
                             type="primary" if is_active else "secondary"):
                    st.session_state.manual_section = label
                    st.rerun()

# =========================================================================
# PANE 2: Upload Resume OR Form Workspace (50% Width)
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
            upgrade_btn = st.button("⚡ Upgrade Resume", type="primary", disabled=uploaded_file is None, use_container_width=True)

            if upgrade_btn and uploaded_file is not None:
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
                            try:
                                detail = response.json().get("detail", response.text)
                            except Exception:
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
            current_section = st.session_state.manual_section
            subtitle_text = SECTION_SUBTITLES.get(current_section, "Fill in candidate credentials and career history")

            st.markdown(f"""
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <div>
                        <h3 style="margin:0; color:#1F2937; font-weight:700;">{current_section}</h3>
                        <span style="font-size:0.84rem; color:#6B7280;">{subtitle_text}</span>
                    </div>
                    <span style="font-size:1.2rem; color:#6B7280;">✏️</span>
                </div>
            """, unsafe_allow_html=True)

            if current_section == "Personal Info":
                st.text_input("Full Name", placeholder="e.g. Jane Doe", key="pi_name")
                col_r, col_l = st.columns(2)
                with col_r:
                    st.text_input("Target Designation", placeholder="e.g. Architect - Data & AI", key="pi_title")
                with col_l:
                    st.text_input("Location / City", placeholder="e.g. Gurugram, India", key="pi_location")

            elif current_section == "Exec Summary":
                st.text_area("Executive Summary", placeholder="Enter structured executive profile overview...",
                             height=240, key="es_summary")

            elif current_section == "Work Experience":
                num_companies = len(st.session_state.companies_data)

                for idx in range(num_companies):
                    comp_data = st.session_state.companies_data[idx]
                    comp_num = idx + 1
                    label = f"Company #{comp_num}" if not comp_data.get("company") else f"Company #{comp_num}: {comp_data['company']}"

                    with st.expander(label, expanded=(idx == 0)):
                        comp_data["company"] = st.text_input(
                            "Company / Organization",
                            value=comp_data.get("company", ""),
                            placeholder="e.g. Insight Direct India Pvt. Ltd.",
                            key=f"we_comp_{idx}",
                        )

                        comp_data["role"] = st.text_input(
                            "Role Title (Most recent designation at this organization)",
                            value=comp_data.get("role", ""),
                            placeholder="e.g. Lead Architect",
                            key=f"we_role_{idx}",
                        )

                        st.markdown("<span style='font-size: 0.85rem; font-weight:600; color:#374151;'>Tenure / Duration</span>", unsafe_allow_html=True)
                        
                        d_col1, d_col2, d_col3, d_col4 = st.columns(4)
                        with d_col1:
                            start_m_idx = MONTHS.index(comp_data.get("start_month", "Jan")) if comp_data.get("start_month") in MONTHS else 0
                            comp_data["start_month"] = st.selectbox("Start Month", MONTHS, index=start_m_idx, key=f"we_sm_{idx}")
                        with d_col2:
                            start_y_val = comp_data.get("start_year", "2023")
                            start_y_idx = YEARS.index(start_y_val) if start_y_val in YEARS else 0
                            comp_data["start_year"] = st.selectbox("Start Year", YEARS, index=start_y_idx, key=f"we_sy_{idx}")
                        
                        comp_data["is_current"] = st.checkbox("Currently working here", value=comp_data.get("is_current", False), key=f"we_curr_{idx}")
                        
                        if not comp_data["is_current"]:
                            with d_col3:
                                end_m_idx = MONTHS.index(comp_data.get("end_month", "Dec")) if comp_data.get("end_month") in MONTHS else 0
                                comp_data["end_month"] = st.selectbox("End Month", MONTHS, index=end_m_idx, key=f"we_em_{idx}")
                            with d_col4:
                                end_y_val = comp_data.get("end_year", "2026")
                                end_y_idx = YEARS.index(end_y_val) if end_y_val in YEARS else 0
                                comp_data["end_year"] = st.selectbox("End Year", YEARS, index=end_y_idx, key=f"we_ey_{idx}")

                        comp_data["bullets"] = st.text_area(
                            "Key Responsibilities & Deliverables (4 to 5 achievements)",
                            value=comp_data.get("bullets", ""),
                            placeholder="• Led migration from Synapse to Fabric, cutting compute cost by 25%\n• Architected medallion data pipelines using PySpark",
                            height=120,
                            key=f"we_bullets_{idx}",
                        )

                        if num_companies > 1:
                            if st.button(f"🗑️ Remove Company #{comp_num}", key=f"del_comp_{idx}", type="secondary"):
                                st.session_state.companies_data.pop(idx)
                                st.rerun()

                st.write("")
                if num_companies < 3:
                    if st.button("➕ Add Experience", use_container_width=True, type="secondary"):
                        st.session_state.companies_data.append({
                            "company": "",
                            "role": "",
                            "start_month": "Jan",
                            "start_year": "2020",
                            "end_month": "Dec",
                            "end_year": "2022",
                            "is_current": False,
                            "bullets": "",
                        })
                        st.rerun()
                else:
                    st.caption("ℹ️ Maximum 3 companies allowed for optimal two-page executive formatting.")

            elif current_section == "Education":
                st.text_input("Institution Name", placeholder="e.g. Delhi University", key="ed_institution")
                col_deg, col_yr = st.columns(2)
                with col_deg:
                    st.text_input("Highest Degree / Major", placeholder="e.g. B.Tech Computer Science", key="ed_degree")
                with col_yr:
                    st.text_input("Year of Completion", placeholder="e.g. 2012", key="ed_year")

            elif current_section == "Areas of Expertise":
                st.text_area("Technical & Functional Domains (10-12 items)",
                             placeholder="Databricks Unity Catalog\nAzure Synapse Analytics\nMicrosoft Fabric\nPySpark & SQL",
                             height=200, key="ax_areas")

            elif current_section == "Certifications":
                st.session_state.selected_certifications = st.multiselect(
                    "Search and select credentials (type code e.g. AZ-900, DP-600, AWS):",
                    options=CERTIFICATION_CATALOG,
                    default=st.session_state.selected_certifications,
                    max_selections=8,
                    help="Maximum 8 certifications allowed to preserve executive template formatting.",
                    key="ce_multiselect",
                )
                if len(st.session_state.selected_certifications) >= 8:
                    st.caption("🔒 Reached maximum limit of 8 certifications.")

            st.write("")
            btn_c1, btn_c2 = st.columns([1, 1])
            with btn_c1:
                st.button("Save Section", type="primary", use_container_width=True)
            with btn_c2:
                st.button("Reset Form", type="secondary", use_container_width=True)

# =========================================================================
# PANE 3: Preview & Download (25% Width)
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
                use_container_width=True,
            )
            if st.button("Start over", type="secondary", use_container_width=True):
                st.session_state.standardized_bytes = None
                st.session_state.resume_filename = ""
                st.rerun()
        else:
            st.info("No document compiled yet. Upload or generate a resume to activate download.")

        st.markdown("""
            <div class="ai-disclaimer">
                <strong>Responsible AI Notice:</strong><br/>
                Content is extracted and structured using generative AI. Verify dates, credentials, and achievements for fidelity prior to client distribution.
            </div>
        """, unsafe_allow_html=True)
