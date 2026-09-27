# Enterprise Resume Builder

A standardized resume-to-Word generation engine built with FastAPI, Streamlit, and `docxtpl`. The system converts unstructured PDF and DOCX CVs into ATS-compliant, branded corporate Word documents with preserved ampersand entities, normalized section taxonomy, and layout-safe pagination.

---

## Architecture Overview

* **Frontend**: Streamlit UI with Microsoft Entra ID (Azure Easy Auth) identity awareness.
* **Backend**: FastAPI REST engine managing payload sanitation, ampersand recovery, and template rendering.
* **LLM Extraction**: OpenAI-compatible router interface (Google Gemini / Azure OpenAI / Groq) outputting structured JSON mapped to Pydantic schemas.
* **Document Engine**: `docxtpl` with Jinja2 syntax running on top of Microsoft Word tables.

---

## Project Structure

```text
resume-standardizer/
│
├── .gitignore
├── README.md
├── requirements.txt
├── startup.sh
│
├── src/
│   ├── app.py                     # FastAPI backend engine
│   ├── ui.py                      # Streamlit UI
│   └── templates/
│       └── ResumeTemplate_Tagged.docx
│
└── prod/                          # Release configs and deployment manifests