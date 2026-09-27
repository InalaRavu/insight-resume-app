import html
import io
import json
import os
from pathlib import Path
import re
from typing import List, Optional

from docx import Document
from docxtpl import DocxTemplate
from fastapi import FastAPI, File, HTTPException, Response, UploadFile
import httpx
from openai import OpenAI
from pydantic import BaseModel, Field
from pypdf import PdfReader
import unicodedata
import xml.etree.ElementTree as ET
import pdfplumber

# 1. Base directory & template path
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE_DIR / "templates" / "ResumeTemplate_Tagged.docx"

app = FastAPI()

# 2. Initialize HF Client via OpenAI router with corporate proxy tolerance
HF_TOKEN = os.getenv("HF_API_KEY")
http_client = httpx.Client(verify=False, trust_env=True, timeout=60.0)

hf_client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_TOKEN,
    http_client=http_client,
)

# 3. Pydantic Schemas
class EducationItem(BaseModel):
    degree: str
    institution: str
    score: Optional[str] = None

class ExperienceItem(BaseModel):
    company: str
    dates: str
    role: str
    client: Optional[str] = ""
    bullet_points: List[str]

class ResumeData(BaseModel):
    name: str
    title: str
    profile: str
    skills: List[str]
    certifications: List[str]
    education: List[EducationItem]
    work_experience: List[ExperienceItem]


# 4. Text Extractor (File Bytes -> Clean Text)
def extract_raw_text(file_bytes: bytes, filename: str) -> str:
    ext = filename.split(".")[-1].lower()
    extracted_text = []

    if ext == "pdf":
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                # Use layout-aware word extraction to prevent sidebar text from slicing through job paragraphs
                text = page.extract_text(layout=True)
                if not text:
                    text = page.extract_text()
                if text:
                    extracted_text.append(text)

    elif ext in ["docx", "doc"]:
        doc = Document(io.BytesIO(file_bytes))

        def _get_element_text(element):
            text_parts = []
            for child in element.iter():
                if child.tag.endswith('t'):
                    text_parts.append(child.text or '')
                elif child.tag.endswith('sym'):
                    char = child.attrib.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}char')
                    if char == '0026':
                        text_parts.append('&')
                elif child.tag.endswith('tab'):
                    text_parts.append(' ')
            return "".join(text_parts)

        for p in doc.paragraphs:
            p_text = _get_element_text(p._p)
            if p_text.strip():
                extracted_text.append(p_text)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        c_text = _get_element_text(p._p)
                        if c_text.strip():
                            extracted_text.append(c_text)
    else:
        raise HTTPException(status_code=400, detail="Unsupported format. Upload PDF or DOCX.")

    raw = "\n".join(extracted_text)

    # Normalize unicode symbols and preserve literal '&'
    normalized = unicodedata.normalize("NFKD", raw)
    normalized = html.unescape(normalized)
    normalized = re.sub(r'[\u200b\u200c\ufeff]', '', normalized)
    return normalized


# 5. Context Preparation & Dictionary Sanitization
# 5. Context Preparation & Dictionary Sanitization
def sanitize_resume_dict(data: dict) -> dict:
    def _clean_str(val: str) -> str:
        if not isinstance(val, str):
            return val

        # Normalize unicode spaces & punctuation
        val = unicodedata.normalize("NFKC", val)
        val = val.replace('\u00a0', ' ').replace('\u200b', '').replace('\ufeff', '')
        val = val.replace('–', '-').replace('—', '-')

        # Guarantee ampersand on target domains
        val = re.sub(r'Data\s*&?\s*AI', 'Data & AI', val, flags=re.IGNORECASE)
        val = re.sub(r'Cloud\s*&?\s*AI', 'Cloud & AI', val, flags=re.IGNORECASE)
        val = re.sub(r'BI\s*&?\s*Reporting', 'BI & Reporting', val, flags=re.IGNORECASE)
        val = re.sub(r'ETL\s*&?\s*Data', 'ETL & Data', val, flags=re.IGNORECASE)
        val = re.sub(r'Sales\s*&?\s*Marketing', 'Sales & Marketing', val, flags=re.IGNORECASE)
        val = re.sub(r'Marketing\s*&?\s*Sales', 'Marketing & Sales', val, flags=re.IGNORECASE)

        # Standardize multiple spaces
        val = re.sub(r'[ \t]{2,}', ' ', val).strip()
        return val

    def _walk(val):
        if isinstance(val, str):
            return _clean_str(val)
        elif isinstance(val, list):
            return [_walk(x) for x in val]
        elif isinstance(val, dict):
            return {k: _walk(v) for k, v in val.items()}
        return val

    cleaned = _walk(data)

    # Force ampersand explicitly on top-level title and profile
    if "title" in cleaned:
        cleaned["title"] = re.sub(r'Data\s*&?\s*AI', 'Data & AI', str(cleaned["title"]), flags=re.IGNORECASE)
    if "profile" in cleaned:
        cleaned["profile"] = re.sub(r'Data\s*&?\s*AI', 'Data & AI', str(cleaned["profile"]), flags=re.IGNORECASE)

    # Universal Experience Validation
    if "work_experience" in cleaned and isinstance(cleaned["work_experience"], list):
        INVALID_COMPANY_KEYWORDS = {
            "leadership", "management", "performance", "methodology", 
            "competencies", "skills", "summary", "responsibilities", 
            "profile", "initiatives", "achievements", "overview"
        }

        valid_exp = []
        for exp in cleaned["work_experience"]:
            comp = exp.get("company", "").strip()
            role = exp.get("role", "").strip()

            # Discard phantom entries that lack a company name or match generic section titles
            if not comp or any(kw in comp.lower() for kw in INVALID_COMPANY_KEYWORDS):
                continue
            
            # Discard entries without bullets or role
            if not role or not exp.get("bullet_points"):
                continue

            # Standardize legal suffixes
            comp = re.sub(r'\bPrivate\s+Limited\b', 'Pvt. Ltd.', comp, flags=re.IGNORECASE)
            comp = re.sub(r'\bPrivate\s+Ltd\.?\b', 'Pvt. Ltd.', comp, flags=re.IGNORECASE)
            comp = re.sub(r'\bLtd\b(?!\.)', 'Ltd.', comp, flags=re.IGNORECASE)

            # Strip trailing location qualifiers (e.g., ", City" or "- City")
            comp = re.sub(r'[,–-]\s*[A-Za-z\s]+$', lambda m: '' if any(loc in m.group(0).lower() for loc in [
                'hyderabad', 'pune', 'bangalore', 'bengaluru', 'mumbai', 'delhi', 
                'noida', 'chennai', 'london', 'new york', 'remote'
            ]) else m.group(0), comp).strip(" .,-")

            exp["company"] = comp

            # Generic role cleanup: drop client suffixes tagged via hyphens ('Role - Client')
            if " - " in role:
                role = role.split(" - ")[0].strip()
            elif " – " in role:
                role = role.split(" – ")[0].strip()
            exp["role"] = role.strip(" .,-")

            # Clean dates
            d = exp.get("dates", "")
            exp["dates"] = d.strip("() ")

            valid_exp.append(exp)

        cleaned["work_experience"] = valid_exp[:3]

    # Skills: Enforce 10-12 items without verbose parentheticals
    if "skills" in cleaned and isinstance(cleaned["skills"], list):
        clean_skills = []
        for s in cleaned["skills"][:12]:
            if isinstance(s, str):
                s_clean = re.sub(r'\(.*?\)', '', s).strip()
                s_clean = s_clean.split(":")[0].strip(" .,-")
                if s_clean:
                    clean_skills.append(s_clean)
        cleaned["skills"] = clean_skills[:12]

    # Certifications: Enforce 6-8 items with clean codes
    if "certifications" in cleaned and isinstance(cleaned["certifications"], list):
        clean_certs = []
        for c in cleaned["certifications"][:8]:
            if isinstance(c, str):
                cert = c.replace("Microsoft Certified: ", "").strip()
                match = re.search(r'\(([A-Z0-9\-\s/]+)\)', cert)
                if match:
                    title_part = cert.split('(')[0].strip()
                    cert = f"{title_part} ({match.group(1)})"
                clean_certs.append(cert.strip(" .,-"))
        cleaned["certifications"] = clean_certs[:8]

    # Format institution line for Word sidebar
    if "education" in cleaned and isinstance(cleaned["education"], list):
        for edu in cleaned["education"]:
            institution = edu.get("institution", "")
            score = edu.get("score")
            edu["institution_line"] = f"{institution} | {score}" if score else institution

    return cleaned
# Restore & and return clean test
def restore_ampersands_from_source(data: dict, raw_text: str) -> dict:
    """
    Extracts authentic '&' phrase pairs directly from source text
    and restores them across the generated resume data.
    """
    if "&" not in raw_text:
        return data

    # 1. Extract clean (word & word) pairs directly from source text
    # e.g., 'Data & AI', 'Sales & Marketing', 'Brand & Communications'
    raw_pairs = re.findall(
        r'(\b[A-Za-z0-9+#]+(?:\s+[A-Za-z0-9+#]+)?)\s*&\s*([A-Za-z0-9+#]+(?:\s+[A-Za-z0-9+#]+)?\b)',
        raw_text
    )

    if not raw_pairs:
        return data

    # 2. Build unambiguous substitution maps
    replacements = []
    for left, right in raw_pairs:
        left = left.strip()
        right = right.strip()
        if left and right and left.lower() != right.lower():
            # Pattern matches left and right separated by 1 or more spaces (or no ampersand)
            pattern = re.compile(
                rf'\b{re.escape(left)}\s+(?:&amp;\s+)?{re.escape(right)}\b',
                flags=re.IGNORECASE
            )
            canonical = f"{left} & {right}"
            replacements.append((pattern, canonical))

    def _apply_restorations(text: str) -> str:
        if not isinstance(text, str):
            return text
        for pattern, canonical in replacements:
            text = pattern.sub(canonical, text)
        return text

    # 3. Apply dynamically to title
    if "title" in data and isinstance(data["title"], str):
        data["title"] = _apply_restorations(data["title"])

    # 4. Apply to profile
    if "profile" in data and isinstance(data["profile"], str):
        data["profile"] = _apply_restorations(data["profile"])

    # 5. Apply to skills list
    if "skills" in data and isinstance(data["skills"], list):
        data["skills"] = [_apply_restorations(s) for s in data["skills"]]

    return data

# 6. Standardize Endpoint (Synchronous def to prevent Swagger freeze)
@app.post("/standardize-resume")
def standardize_resume(file: UploadFile = File(...)):
    if not TEMPLATE_PATH.exists():
        raise HTTPException(status_code=500, detail=f"Template not found at: {TEMPLATE_PATH}")

    # Read and extract raw text from upload
    file_bytes = file.file.read()
    raw_text = extract_raw_text(file_bytes, file.filename)

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from document.")

    system_prompt = f"""
    You are an executive resume writer and ATS standardization engine.
    Extract and normalize the resume text strictly into valid JSON matching this schema:
    {json.dumps(ResumeData.model_json_schema())}

    Strict Extraction & Formatting Rules:
    1. Text Fidelity & Ampersands:
       - Output the literal character '&' in titles and domains (write 'Data & AI', 'BI & Reporting', 'ETL & Data').
    2. Skills Guidelines:
       - Extract strictly 10 to 12 skills.
       - ORDER: Place the most specialized, high-demand NICHE skills at the top, descending to foundational competencies at the bottom (e.g., 'Agentic AI Systems', 'Databricks Unity Catalog', 'Synapse Analytics' FIRST, ending with broader skills like 'SQL', 'Python').
       - Keep each skill short and punchy (maximum 2 to 4 words). Do NOT include lengthy parenthetical explanations or paragraphs.
    3. Certifications Guidelines:
       - Extract strictly 6 to 8 certifications.
       - ORDER: Rank by technical prestige and specialization from top to bottom (e.g., Expert/Specialty/Architecture certifications FIRST like 'Azure Solutions Architect Expert (AZ-305)', 'DevOps Engineer Expert (AZ-400)', 'Fabric Analytics Engineer (DP-600)', descending to associate and fundamentals like 'AZ-900').
       - Strip redundant provider prefixes like 'Microsoft Certified:' to keep lines concise.
    . Work Experience Guidelines (Strictly use key 'work_experience'):
       - Identify and extract the candidate's core professional employment history (maximum 3 most recent or most relevant organizations).
       - STRICT BOUNDARY RULE:
         * A valid experience entry MUST represent a direct corporate employer or recognized client organization.
         * NEVER treat standalone skill headings, functional capability sections, or thematic blocks (such as 'LEADERSHIP, PERFORMANCE & TEAM MANAGEMENT', 'METHODOLOGY', 'KEY INITIATIVES', or 'AREAS OF EXPERTISE') as company names.
         * If the source document contains standalone leadership, delivery, or management achievements, synthesize and fold those points into the bullet points of the respective employer where they occurred.
       - 'company': The clean, official organization name (retain legal suffixes like 'Pvt. Ltd.', 'Ltd.', 'LLC', 'Inc.' if present in source).
       - 'dates': Normalized tenure string (e.g., 'Apr 2024 - Present', 'Feb 2007 - Apr 2015').
       - 'role': ONLY the candidate's single highest/latest official designation at that organization. Do NOT append client names (e.g., do NOT write 'Lead - ClientName' or 'Role (ClientName)').
       - 'bullet_points': Exactly 4 to 5 quantitative, high-impact achievement bullets per organization. Start each with a strong action verb. Keep each bullet to 1 to 2 lines max.

    Return pure JSON only.
    """

    try:
        completion = hf_client.chat.completions.create(
            model="Qwen/Qwen2.5-72B-Instruct",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Resume Text:\n{raw_text}"},
            ],
            temperature=0.1,
            max_tokens=2500,
        )

        raw_response = completion.choices[0].message.content.strip()

        # Strip markdown code blocks if returned
        if raw_response.startswith("```"):
            raw_response = re.sub(r"^```(?:json)?\n?", "", raw_response)
            raw_response = re.sub(r"\n?```$", "", raw_response)

        parsed_data = ResumeData.model_validate_json(raw_response)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"HF Extraction error: {str(e)}")

    # Prepare cleaned context & render template
    render_context = sanitize_resume_dict(parsed_data.model_dump())
    render_context = restore_ampersands_from_source(render_context, raw_text)

    # Render into Word Template
    doc = DocxTemplate(str(TEMPLATE_PATH))
    doc.render(render_context)

    # Stream the output docx
    output_stream = io.BytesIO()
    doc.save(output_stream)
    output_stream.seek(0)

    base_name = Path(file.filename).stem
    download_filename = f"Standardized_{base_name}.docx"

    return Response(
        content=output_stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{download_filename}"'
        },
    )