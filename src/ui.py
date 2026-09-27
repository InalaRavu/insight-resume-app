import streamlit as st
import httpx
from pathlib import Path

st.set_page_config(page_title="Executive Resume Standardizer", layout="centered")

st.title("📄 Executive Resume Standardizer")
st.write("Upload a raw resume (DOCX or PDF) to convert it into the standardized branded ATS format.")

uploaded_file = st.file_uploader("Upload Resume", type=["docx", "doc", "pdf"])

if uploaded_file is not None:
    if st.button("Generate Standardized Resume", type="primary"):
        with st.spinner("Analyzing document, standardizing layout, and restoring entities..."):
            try:
                files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                
                # Point to your local or deployed FastAPI service
                response = httpx.post("http://localhost:8000/standardize-resume", files=files, timeout=90.0)
                
                if response.status_code == 200:
                    base_name = Path(uploaded_file.name).stem
                    out_filename = f"Standardized_{base_name}.docx"
                    
                    st.success("✅ Standardization Complete!")
                    st.download_button(
                        label="📥 Download Standardized Resume (.docx)",
                        data=response.content,
                        file_name=out_filename,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    )
                else:
                    st.error(f"Error ({response.status_code}): {response.text}")
            except Exception as e:
                st.error(f"Failed to connect to service: {str(e)}")