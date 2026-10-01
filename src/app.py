import html
import io
import json
import logging
import os
from pathlib import Path
import re
from typing import List, Optional
import unicodedata

import pdfplumber
from docx import Document
from docxtpl import DocxTemplate
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel, Field

from src import config, llm  # config loads .env before any constant below is read
from src.auth import AuthError, Principal, principal_from_headers
from src.utils import (
    TIER_NAMES,
    highest_tier_in_text,
    rank_qualification,
    select_top_qualification,
)

# 1. Base directory & template path
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE_DIR / "templates" / "ResumeTemplate_Tagged.docx"
ROOT_DIR = config.ROOT_DIR

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("nexa.app")

MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = int(MAX_UPLOAD_MB * 1024 * 1024)
# Long resumes overflow a small completion budget, which truncates the JSON and
# surfaces as an opaque parse failure. 8k covers a dense 4-page CV.
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8000"))

# Page-1 left pane capacity. The pane is a table cell; if its content outgrows
# the page the single-row table splits across the page boundary and the cell
# bleeds alongside the right pane. These caps keep it inside one page.
MAX_SKILLS = int(os.getenv("MAX_SKILLS", "12"))
MAX_CERTIFICATIONS = int(os.getenv("MAX_CERTIFICATIONS", "7"))
PROFILE_MAX_WORDS = int(os.getenv("PROFILE_MAX_WORDS", "70"))

# Page 1 right pane: career highlights. Wider than the left pane, so it holds
# more than the left column's list sections.
MAX_EXPERIENCE_SUMMARY_BULLETS = int(os.getenv("MAX_EXPERIENCE_SUMMARY_BULLETS", "10"))

# Achievements requested per company. This is the single biggest driver of how
# many tokens the model has to generate, and therefore of how long the request
# takes. The HuggingFace free router returns 504 from its own gateway on long
# generations, so asking for less is what keeps a large resume inside its limit.
MAX_ACHIEVEMENTS_PER_COMPANY = int(os.getenv("MAX_ACHIEVEMENTS_PER_COMPANY", "5"))

# Page-2 capacity for PROFESSIONAL EXPERIENCE, calibrated against Word rather
# than derived from page geometry. With page 1 maximally filled, page 2 holds 40
# lines; 44 spills to a third page. Verified at both extremes -- single-line
# bullets (where the estimate equals the real line count) and long wrapped ones.
#
# The wrap width stays below the true ~90 characters so the estimate over-counts
# wrapped text, which is the margin that makes a budget of exactly 40 safe.
# Re-calibrate after any template or font change:
#   python tools/page_count.py <rendered>.docx
EXPERIENCE_LINE_BUDGET = int(os.getenv("EXPERIENCE_LINE_BUDGET", "40"))
EXPERIENCE_CHARS_PER_LINE = int(os.getenv("EXPERIENCE_CHARS_PER_LINE", "85"))
# Employers shown in PROFESSIONAL EXPERIENCE, most recent first. Older roles are
# dropped rather than compressed: a 20-year career lists jobs whose detail has
# stopped being relevant, and the space buys fuller achievements for the recent
# ones. Raise this to show more history.
MAX_COMPANIES = int(os.getenv("MAX_COMPANIES", "3"))

# Achievements per company when the section will not otherwise fit, tried most
# generous first. Every company shown keeps its heading; only bullets give way.
COMPANY_BULLET_STEPS = (5, 4, 3, 2)

app = FastAPI(title="NEXA Resume Builder API", version="1.1.0")


# 2. Authenticated principal (Easy Auth headers, or dev identity locally)
def current_principal(request: Request) -> Principal:
    try:
        return principal_from_headers(request.headers)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# 3. Pydantic Schemas
class WorkHistory(BaseModel):
    """One employer.

    Deliberately flat. An earlier schema nested projects under each employer,
    but the model filled the project's client with the company name and its role
    with a sentence of responsibilities, producing a duplicated heading. The
    rendered layout is company / role / achievements, so the schema matches it.
    """

    company_name: str = Field(description="Company or employer name, nothing else")
    overall_title: str = Field(description="Job title held at this company, e.g. 'Practice Manager - Data'")
    duration: str = Field(description="Tenure at company (e.g., Nov 2022 - Mar 2026)")
    achievements: List[str] = Field(
        default_factory=list,
        description="4 to 5 significant quantified achievements across all work at this company",
    )


class EducationItem(BaseModel):
    degree: str
    institution: str
    score: Optional[str] = None


class ResumeData(BaseModel):
    full_name: str
    headline: str
    profile_summary: str
    skills: List[str] = Field(default_factory=list)
    education: List[EducationItem] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    experience_summary_bullets: List[str] = Field(
        default_factory=list,
        description="3 to 4 comprehensive synthesized paragraphs highlighting core career domains for Page 1 right pane",
    )
    work_experience: List[WorkHistory] = Field(default_factory=list)


# 4. Text Extractor (File Bytes -> Clean Text)
def extract_raw_text(file_bytes: bytes, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    extracted_text = []

    if ext == "pdf":
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text(layout=True)
                if not text:
                    text = page.extract_text()
                if text:
                    extracted_text.append(text)

    elif ext == "docx":
        try:
            doc = Document(io.BytesIO(file_bytes))
        except Exception as exc:  # noqa: BLE001 - surface a readable cause
            raise HTTPException(
                status_code=400,
                detail="This file could not be opened as a .docx. If it is a legacy .doc, "
                       "open it in Word and re-save as .docx, then upload again.",
            ) from exc

        # Match the WordprocessingML tags exactly. Testing endswith('t') also
        # matches drawing elements such as <wp:posOffset> and <wp:extent>, which
        # injected raw layout coordinates into the text ("848995109855Oct'05...").
        W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        W_T, W_TAB, W_SYM, W_BR = W + 't', W + 'tab', W + 'sym', W + 'br'

        def _get_element_text(element):
            text_parts = []
            for child in element.iter():
                if child.tag == W_T:
                    text_parts.append(child.text or '')
                elif child.tag == W_SYM:
                    if child.attrib.get(W + 'char') == '0026':
                        text_parts.append('&')
                elif child.tag in (W_TAB, W_BR):
                    text_parts.append(' ')
            return "".join(text_parts)

        def _walk_table(table, seen_cells):
            """Yield each cell's text once.

            python-docx returns a merged cell once per grid position it spans,
            so a CV laid out in a table with merged cells extracts two to four
            times over. That multiplies the prompt and misleads the model --
            one resume reported twelve employers for six real ones.

            seen_cells maps id -> element rather than holding bare ids: lxml
            builds element proxies on demand, so once a proxy is garbage
            collected its id can be reused by a different cell. Keeping the
            element referenced pins the id for the duration of the walk.
            """
            for row in table.rows:
                for cell in row.cells:
                    tc = cell._tc
                    key = id(tc)
                    if key in seen_cells:
                        continue
                    seen_cells[key] = tc
                    for p in cell.paragraphs:
                        c_text = _get_element_text(p._p)
                        if c_text.strip():
                            yield c_text
                    for nested in cell.tables:
                        yield from _walk_table(nested, seen_cells)

        for p in doc.paragraphs:
            p_text = _get_element_text(p._p)
            if p_text.strip():
                extracted_text.append(p_text)

        seen_cells = {}
        for table in doc.tables:
            extracted_text.extend(_walk_table(table, seen_cells))

    elif ext == "doc":
        raise HTTPException(
            status_code=400,
            detail="Legacy .doc files are not supported. Open the file in Word and "
                   "use 'Save As' to produce a .docx, then upload that.",
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported format. Upload a PDF or DOCX file.")

    raw = "\n".join(extracted_text)
    normalized = unicodedata.normalize("NFKD", raw)
    normalized = html.unescape(normalized)
    normalized = re.sub(r'[​‌﻿]', '', normalized)
    return normalized


# 5. Context Sanitization
def sanitize_resume_dict(data: dict) -> dict:
    def _clean_str(val: str) -> str:
        if not isinstance(val, str):
            return val
        val = unicodedata.normalize("NFKC", val)
        val = val.replace(' ', ' ').replace('​', '').replace('﻿', '')
        val = val.replace('–', '-').replace('—', '-')
        val = re.sub(r'Data\s*&?\s*AI', 'Data & AI', val, flags=re.IGNORECASE)
        val = re.sub(r'Cloud\s*&?\s*AI', 'Cloud & AI', val, flags=re.IGNORECASE)
        val = re.sub(r'BI\s*&?\s*Reporting', 'BI & Reporting', val, flags=re.IGNORECASE)
        val = re.sub(r'ETL\s*&?\s*Data', 'ETL & Data', val, flags=re.IGNORECASE)
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

    # Standardize skills
    if isinstance(cleaned.get("skills"), list):
        clean_skills = []
        for s in cleaned["skills"][:MAX_SKILLS]:
            if isinstance(s, str):
                s_clean = re.sub(r'\(.*?\)', '', s).strip().split(":")[0].strip(" .,-")
                if s_clean:
                    clean_skills.append(s_clean)
        cleaned["skills"] = clean_skills[:MAX_SKILLS]

    # Standardize certifications
    if isinstance(cleaned.get("certifications"), list):
        clean_certs = []
        for c in cleaned["certifications"][:MAX_CERTIFICATIONS]:
            if isinstance(c, str):
                cert = c.replace("Microsoft Certified: ", "").strip(" .,-")
                if cert:
                    clean_certs.append(cert)
        cleaned["certifications"] = clean_certs[:MAX_CERTIFICATIONS]

    if isinstance(cleaned.get("work_experience"), list):
        for comp in cleaned["work_experience"]:
            if isinstance(comp, dict) and isinstance(comp.get("achievements"), list):
                comp["achievements"] = comp["achievements"][:MAX_ACHIEVEMENTS_PER_COMPANY]

    return cleaned


def restore_ampersands_from_source(data: dict, raw_text: str) -> dict:
    if "&" not in raw_text:
        return data

    raw_pairs = re.findall(
        r'(\b[A-Za-z0-9+#]+(?:\s+[A-Za-z0-9+#]+)?)\s*&\s*([A-Za-z0-9+#]+(?:\s+[A-Za-z0-9+#]+)?\b)',
        raw_text
    )
    if not raw_pairs:
        return data

    replacements = []
    for left, right in raw_pairs:
        left, right = left.strip(), right.strip()
        if left and right and left.lower() != right.lower():
            pattern = re.compile(rf'\b{re.escape(left)}\s+(?:&amp;\s+)?{re.escape(right)}\b', flags=re.IGNORECASE)
            replacements.append((pattern, f"{left} & {right}"))

    def _apply_restorations(text: str) -> str:
        if not isinstance(text, str):
            return text
        for pattern, canonical in replacements:
            text = pattern.sub(canonical, text)
        return text

    if isinstance(data.get("headline"), str):
        data["headline"] = _apply_restorations(data["headline"])
    if isinstance(data.get("profile_summary"), str):
        data["profile_summary"] = _apply_restorations(data["profile_summary"])
    if isinstance(data.get("skills"), list):
        data["skills"] = [_apply_restorations(s) for s in data["skills"]]

    return data


# 6. Template contract
#
# The .docx template uses short tag names that deliberately differ from the
# extraction schema (the template is authored by non-engineers in Word). Mapping
# them here -- rather than renaming schema fields -- keeps the LLM contract and
# the document contract independently versionable.
TEMPLATE_VARIABLES = {
    "name", "title", "profile", "skills", "education",
    "certifications", "experience_summary_bullets", "work_experience",
}


def _compose_institution_line(institution: Optional[str], score: Optional[str]) -> str:
    institution = (institution or "").strip()
    score = (score or "").strip()
    if institution and score:
        return f"{institution} | {score}"
    return institution or score


# --- Page 1: headline and profile normalisation -----------------------------

# Clauses that turn a job title into a sentence. Everything from here on is
# biography, not a title: "Data Engineering Manager with over 17 years of
# experience" must render as "Data Engineering Manager".
_TITLE_TAIL = re.compile(
    r'\s+(?:with|having|possessing|offering|bringing|over|experienced)\b.*$',
    re.IGNORECASE,
)
_TITLE_YEARS = re.compile(r'\s*[-–—,|(]?\s*(?:over|more than|nearly)?\s*\d+\+?\s*years?\b.*$', re.IGNORECASE)


def _clean_job_title(headline: Optional[str]) -> str:
    """Reduce an extracted headline to the job title alone."""
    title = (headline or "").strip()
    if not title:
        return ""
    title = _TITLE_YEARS.sub("", title)
    title = _TITLE_TAIL.sub("", title)
    # Keep only the first segment of a pipe/bullet separated strapline.
    title = re.split(r'\s*[|•·]\s*', title)[0]
    title = title.strip(" .,-–—|·")
    # A title is a noun phrase; anything much longer is a summary sentence.
    words = title.split()
    if len(words) > 8:
        title = " ".join(words[:8])
    return title


def _trim_profile(text: Optional[str], max_words: int = None) -> str:
    """Trim the profile to an ATS-appropriate length on a sentence boundary."""
    max_words = PROFILE_MAX_WORDS if max_words is None else max_words
    profile = re.sub(r'\s+', ' ', (text or "").strip())
    if not profile:
        return ""
    if len(profile.split()) <= max_words:
        return profile

    sentences = re.split(r'(?<=[.!?])\s+', profile)
    kept, total = [], 0
    for sentence in sentences:
        words = len(sentence.split())
        if kept and total + words > max_words:
            break
        kept.append(sentence)
        total += words
    result = " ".join(kept).strip()

    # A single opening sentence can itself exceed the budget; cut on a word.
    if len(result.split()) > max_words:
        result = " ".join(result.split()[:max_words]).rstrip(" ,;:-") + "."
    return result


# --- Page 2: fitting PROFESSIONAL EXPERIENCE onto one page ------------------

_IMPACT_VERB = re.compile(
    r'\b(led|managed|delivered|built|architected|migrated|reduced|increased|improved|'
    r'boosted|automated|designed|spearheaded|launched|saved|optimi[sz]\w*|scaled|'
    r'implemented|established|transformed)\b',
    re.IGNORECASE,
)


def _wrapped_lines(text: str) -> int:
    """How many rendered lines a paragraph of this length occupies."""
    if not text:
        return 0
    return max(1, -(-len(text) // EXPERIENCE_CHARS_PER_LINE))


def _estimate_experience_lines(companies: List[dict]) -> int:
    """Rendered lines for the section: company line + role line + bullets."""
    total = 0
    for comp in companies:
        # Name and dates share one line via a right-aligned tab stop.
        total += _wrapped_lines(f"{comp['company_name']}  {comp['duration']}")
        total += _wrapped_lines(comp["role"])
        for bullet in comp["achievements"]:
            total += _wrapped_lines(bullet)
    return total


def _dedupe_bullets(bullets: List[str]) -> List[str]:
    """Drop repeats. Models often restate the same achievement per engagement."""
    seen, unique = set(), []
    for bullet in bullets:
        key = re.sub(r'[^a-z0-9]+', ' ', bullet.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(bullet)
    return unique


def _significance(bullet: str) -> float:
    """Rank achievements so trimming keeps the quantified, high-impact ones."""
    score = 0.0
    if re.search(r'\d', bullet):
        score += 3.0
    if re.search(r'[%$£€]|percent', bullet, re.IGNORECASE):
        score += 2.0
    if _IMPACT_VERB.search(bullet):
        score += 1.5
    score += min(len(bullet) / 120.0, 1.0)  # mild preference for substance
    return score


def _select_significant(bullets: List[str], limit: int) -> List[str]:
    if len(bullets) <= limit:
        return bullets
    ranked = sorted(range(len(bullets)), key=lambda i: (-_significance(bullets[i]), i))[:limit]
    return [bullets[i] for i in sorted(ranked)]  # restore original order


def _limit_company_bullets(companies: List[dict], max_bullets: int) -> List[dict]:
    return [
        {**comp, "achievements": _select_significant(comp["achievements"], max_bullets)}
        for comp in companies
    ]


def fit_experience_to_page(companies: List[dict]) -> List[dict]:
    """Return the fullest experience section that still fits one page.

    Only the bullet count per company gives way -- every employer is kept, even
    if that means spilling onto a third page, because dropping an employer
    leaves a gap in the career history.
    """
    if not companies:
        return companies

    for max_bullets in COMPANY_BULLET_STEPS:
        candidate = _limit_company_bullets(companies, max_bullets)
        lines = _estimate_experience_lines(candidate)
        if lines <= EXPERIENCE_LINE_BUDGET:
            log.info(
                "Experience fits at %d achievements per company (~%d lines).",
                max_bullets, lines,
            )
            return candidate

    fewest = COMPANY_BULLET_STEPS[-1]
    log.warning(
        "Experience exceeds the %d-line budget even at %d achievements per company; "
        "all %d employers kept, may spill to a third page.",
        EXPERIENCE_LINE_BUDGET, fewest, len(companies),
    )
    return _limit_company_bullets(companies, fewest)


def _prepare_companies(raw: Optional[List[dict]]) -> List[dict]:
    """Normalise work history into the shape the template renders.

    De-duplication is global, not per company: models reuse a generic bullet
    ("played a key role in developing a data governance framework") under two
    different employers, and the same sentence appearing twice on one page reads
    as carelessness. The earliest employer keeps it.
    """
    prepared, seen = [], set()
    for comp in raw or []:
        achievements = []
        for item in comp.get("achievements") or []:
            text = str(item).strip()
            if not text:
                continue
            key = re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()
            if key and key not in seen:
                seen.add(key)
                achievements.append(text)
        entry = {
            "company_name": (comp.get("company_name") or "").strip(),
            "duration": (comp.get("duration") or "").strip(),
            "role": (comp.get("overall_title") or "").strip(),
            "achievements": achievements,
        }
        # An employer whose every bullet was a duplicate of an earlier one is a
        # model failure: it copied another employer's achievements wholesale.
        # Those bullets are factually wrong here, so they cannot be kept -- but a
        # heading with nothing under it looks broken, so the employer is dropped
        # and the next one takes its place.
        if not entry["achievements"]:
            log.warning(
                "Dropping %r from experience: no achievements survived de-duplication, "
                "which means the model reused another employer's bullets.",
                entry["company_name"] or "<unnamed company>",
            )
            continue
        prepared.append(entry)
    return prepared


def build_render_context(data: dict) -> dict:
    """Translate the extraction schema into the template's variable names."""
    return {
        "name": data.get("full_name", ""),
        "title": _clean_job_title(data.get("headline")),
        "profile": _trim_profile(data.get("profile_summary")),
        "skills": list(data.get("skills") or [])[:MAX_SKILLS],
        "certifications": list(data.get("certifications") or [])[:MAX_CERTIFICATIONS],
        "experience_summary_bullets":
            list(data.get("experience_summary_bullets") or [])[:MAX_EXPERIENCE_SUMMARY_BULLETS],
        "education": [
            {
                "degree": (edu.get("degree") or "").strip(),
                "institution_line": _compose_institution_line(edu.get("institution"), edu.get("score")),
            }
            for edu in (data.get("education") or [])
        ],
        # Cap before fitting, so the surviving employers compete for the page
        # against each other rather than against history that will not be shown.
        "work_experience": fit_experience_to_page(
            _prepare_companies(data.get("work_experience"))[:MAX_COMPANIES]
        ),
    }


def _strict_jinja_env() -> Environment:
    """Two deliberate choices here:

    StrictUndefined turns a template/context mismatch into a loud error instead
    of a silently blank field -- the failure mode this app shipped with.

    autoescape=True is required for correctness, not just hygiene. docxtpl
    defaults it to False, which injects raw '&', '<' and '>' into document.xml
    and silently corrupts the output -- an '&' in 'Data & AI' simply vanishes in
    the rendered document.
    """
    return Environment(undefined=StrictUndefined, autoescape=True)


# Cached template bytes, keyed by modification time.
#
# This project lives in a OneDrive-synced folder, and both OneDrive and Word
# take transient exclusive locks on the .docx -- which surfaced as a 500 midway
# through a run. Serving from a cached copy makes those locks invisible while
# still picking up genuine template edits, which change the mtime.
_template_cache: Optional[tuple] = None


def _load_template() -> DocxTemplate:
    """Return the template, preferring a fresh read but tolerating a locked file."""
    global _template_cache

    if not TEMPLATE_PATH.exists():
        raise HTTPException(status_code=500, detail=f"Template not found at: {TEMPLATE_PATH}")

    try:
        mtime = TEMPLATE_PATH.stat().st_mtime
    except OSError:
        mtime = None

    if _template_cache is None or mtime is None or mtime != _template_cache[0]:
        try:
            data = TEMPLATE_PATH.read_bytes()
            DocxTemplate(io.BytesIO(data))  # validate before caching
            _template_cache = (mtime, data)
        except Exception as exc:  # noqa: BLE001
            if _template_cache is None:
                raise HTTPException(
                    status_code=503,
                    detail="The resume template could not be opened. It is most likely open "
                           "in Microsoft Word, or being synced by OneDrive -- close it and "
                           f"try again. ({type(exc).__name__}: {exc})",
                ) from exc
            log.warning("Template temporarily unreadable (%s); serving the cached copy.", exc)

    return DocxTemplate(io.BytesIO(_template_cache[1]))


def render_resume(context: dict) -> bytes:
    doc = _load_template()
    try:
        doc.render(context, _strict_jinja_env(), autoescape=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="Template rendering failed -- the template expects a field the data does "
                   f"not provide: {exc}",
        ) from exc
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def template_contract_report() -> dict:
    """Compare the tags actually present in the .docx against what we supply."""
    try:
        declared = set(DocxTemplate(str(TEMPLATE_PATH)).get_undeclared_template_variables())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    missing = sorted(declared - TEMPLATE_VARIABLES)
    return {
        "ok": not missing,
        "template_variables": sorted(declared),
        "unsatisfied": missing,
    }


# 7. LLM extraction
EXTRACTION_RULES = """
You are an executive resume writer and ATS standardization engine.
Extract and normalize the resume text strictly into valid JSON matching this schema:
{schema}

Strict Extraction & Formatting Rules:
1. Output literal '&' where appropriate ('Data & AI', 'BI & Reporting').
2. headline: the JOB TITLE ONLY, 2 to 5 words, as it would appear on a business card.
   Correct: "Data Engineering Manager". Wrong: "Data Engineering Manager with over
   17 years of experience". Never include years of experience, skills or any clause.
3. profile_summary: 3 to 4 sentences, 70 words MAXIMUM, written to ATS conventions --
   seniority, core domain, technologies, measurable scale. No first person, no filler.
4. Skills: Extract 10 to 12 skills. High-demand niche skills at top descending to foundational.
5. Certifications: Extract up to {max_certifications} items, prioritized by prestige.
6. Experience Summary Bullets (Page 1 Right Pane): Provide 8 to {max_summary_bullets}
   synthesized career highlights covering core domain expertise (e.g. Modern Cloud
   Platforms, Migrations, AI Solutions), leadership scale and measurable business
   outcomes. One sentence each, 25 words maximum per sentence.
7. Work Experience (Page 2 Full Width) -- one entry per EMPLOYER:
   - List employers MOST RECENT FIRST. Include every employer found; they are
     truncated later, so ordering matters more than count.
   - company_name: the employer's name ONLY. Not a client, not a role, not a domain.
     Correct: "Insight Direct". Wrong: "Client Domain: Healthcare (Managed Service)".
   - overall_title: the JOB TITLE held there, 2 to 6 words, and where an employer
     lists a progression or "Growth Path" of several roles, use the LATEST one --
     the role with the most recent dates, not the last line printed and not the
     most senior-sounding. Example: for
         Team Lead - Event Detection (British Telecom)   Feb'07-Mar'10
         Project Manager and Technical Lead (Shell)      Apr'10-Jun'13
         Lead - Service Improvement (Sealed Air)         Aug'13-Sep'13
         Consultant - TechOps IT (Novartis)              Dec'13-Mar'15
     the correct overall_title is "Consultant - TechOps IT", because Dec'13-Mar'15
     is the latest period. Never output a sentence describing duties.
   - duration: the FULL tenure at that employer -- earliest start to latest end
     across every role held there. This is NOT the latest role's dates. For the
     Growth Path above, under a heading "Feb'07-Apr'15 with Wipro Ltd.", the
     duration is "Feb 2007 - Apr 2015", even though the latest role ran
     Dec'13-Mar'15. Take the employer's own heading dates whenever they are given.
   - achievements: ALWAYS 4 to {max_achievements} bullets per employer, merged from
     every project and client at that employer. Do NOT list projects separately.
     4 is the MINIMUM. If the source gives fewer, draw further bullets from the
     responsibilities, tools and clients described under that employer until there
     are at least 4. Only go below 4 if the source truly says less.
   - Order bullets strongest first: quantified outcomes (%, headcount, volume, cost)
     before scope and responsibility statements.
   - Each bullet must be ONE sentence, 25 words maximum, and should name the client or
     domain inline where it adds meaning (e.g. "For a healthcare client, ...").
   - Achievements MUST describe work actually done at THAT employer, in that period.
     Never copy or reword a bullet from another employer. Technologies that did not
     exist during an employer's tenure cannot appear under it. If an employer has
     only two genuine achievements in the source, return two -- returning five by
     reusing another employer's bullets is a serious error.
8. education: list EVERY qualification found, highest first. Include degrees even when the
   source lists them only in a table, sidebar or abbreviated form (B.Tech, B.Sc, MCA, MBA).
9. Never invent facts. If a field is absent from the source, return an empty string or empty list.

Return pure JSON only, with no prose and no markdown fences.
"""


def _strip_code_fences(text: str) -> str:
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_object(text: str) -> str:
    """Pull the outermost JSON object out of a response that may carry stray prose."""
    text = _strip_code_fences(text)
    start = text.find("{")
    if start == -1:
        return text
    depth, in_string, escaped = 0, False, False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    # Unbalanced => the completion was cut off mid-object.
    return text[start:]


def _bullet_key(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', str(text).lower()).strip()


def _extract_json_array(text: str) -> str:
    """Pull the outermost JSON array out of a response that may carry prose."""
    text = _strip_code_fences(text)
    start = text.find("[")
    if start == -1:
        return "[]"
    depth, in_string, escaped = 0, False, False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return "[]"


def repair_duplicated_achievements(data: "ResumeData", raw_text: str) -> "ResumeData":
    """Re-extract achievements for employers whose bullets were copied wholesale.

    The model intermittently fills a later employer with an earlier one's
    achievements verbatim -- a 2007-2015 role credited with Databricks Unity
    Catalog work. Those bullets are factually wrong, so they cannot be shown,
    but dropping the employer loses real career history. One targeted follow-up
    per affected employer is cheap (a short generation) and only runs when the
    copy actually happens.
    """
    seen: set = set()
    for company in data.work_experience:
        keys = {_bullet_key(a) for a in company.achievements if str(a).strip()}
        if not keys:
            continue
        if not keys - seen:  # every bullet already belongs to an earlier employer
            log.warning(
                "%r reused another employer's achievements; re-extracting just that employer.",
                company.company_name,
            )
            replacement = _reextract_company_achievements(company, raw_text)
            if replacement:
                company.achievements = replacement
                keys = {_bullet_key(a) for a in replacement}
            else:
                company.achievements = []
                keys = set()
        seen |= keys
    return data


def _reextract_company_achievements(company, raw_text: str) -> List[str]:
    """Ask for one employer's achievements in isolation. Returns [] on failure."""
    system_prompt = (
        "You extract achievements for ONE employer from a resume. Return ONLY a JSON "
        "array of 3 to 5 strings, each a single sentence of 25 words maximum describing "
        "work done at that employer during that period. Use only facts present in the "
        "text. Do not include work from any other employer. No prose, no markdown."
    )
    user_prompt = (
        f"Employer: {company.company_name}\n"
        f"Role: {company.overall_title}\n"
        f"Period: {company.duration}\n\n"
        f"Resume text:\n{raw_text}"
    )
    try:
        raw = llm.complete(system_prompt, user_prompt, max_tokens=800, attempts_per_provider=1)
        items = json.loads(_extract_json_array(raw))
    except Exception as exc:  # noqa: BLE001 - a failed repair must not fail the request
        log.warning("Re-extraction for %r failed: %s", company.company_name, exc)
        return []
    return [str(i).strip() for i in items if isinstance(i, (str, int, float)) and str(i).strip()][:MAX_ACHIEVEMENTS_PER_COMPANY]


def _warn_if_qualification_looks_missed(chosen, raw_text: str) -> None:
    """Flag a likely extraction miss in the education section.

    The ranking only sees what the model returned. If the source resume mentions
    a higher qualification than the one selected, the model dropped it -- which
    shows up as a school qualification on the resume of a senior candidate.
    Logged rather than corrected: inventing an institution would be worse.
    """
    chosen_tier = rank_qualification(chosen)
    source_tier = highest_tier_in_text(raw_text)
    if source_tier > chosen_tier:
        degree = getattr(chosen, "degree", None) or (
            chosen.get("degree") if isinstance(chosen, dict) else chosen
        )
        log.warning(
            "Education may be under-extracted: rendered %r (%s) but the source text "
            "mentions %s. Check the resume's education section.",
            degree, TIER_NAMES.get(chosen_tier, chosen_tier),
            TIER_NAMES.get(source_tier, source_tier),
        )


def build_extraction_prompt() -> str:
    """Render the system prompt. Single source of truth for its placeholders."""
    return EXTRACTION_RULES.format(
        schema=json.dumps(ResumeData.model_json_schema()),
        max_certifications=MAX_CERTIFICATIONS,
        max_achievements=MAX_ACHIEVEMENTS_PER_COMPANY,
        max_summary_bullets=MAX_EXPERIENCE_SUMMARY_BULLETS,
    )


def extract_resume_data(raw_text: str) -> ResumeData:
    system_prompt = build_extraction_prompt()
    try:
        raw_response = llm.complete(
            system_prompt,
            f"Resume Text:\n{raw_text}",
            max_tokens=LLM_MAX_TOKENS,
        )
    except llm.AllProvidersFailed as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    candidate = _extract_json_object(raw_response)
    try:
        return ResumeData.model_validate_json(candidate)
    except Exception as exc:  # noqa: BLE001
        log.error("Could not parse model output: %s", candidate[:500])
        raise HTTPException(
            status_code=502,
            detail="The AI response was not valid resume JSON (it may have been truncated). "
                   f"Try again, or raise LLM_MAX_TOKENS. Parser said: {exc}",
        ) from exc


# 8. Endpoints
@app.get("/health")
def health():
    return {
        "status": "ok",
        "template_present": TEMPLATE_PATH.exists(),
        "template_contract": template_contract_report(),
        "llm_providers": llm.chain_status(),
    }


@app.get("/me")
def me(principal: Principal = Depends(current_principal)):
    return {
        "email": principal.email,
        "display_name": principal.display_name,
        "is_dev_identity": principal.is_dev_identity,
    }


@app.post("/standardize-resume")
def standardize_resume(
    file: UploadFile = File(...),
    principal: Principal = Depends(current_principal),
):
    if not TEMPLATE_PATH.exists():
        raise HTTPException(status_code=500, detail=f"Template not found at: {TEMPLATE_PATH}")

    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is {len(file_bytes) / 1048576:.1f} MB; the limit is {MAX_UPLOAD_MB:.0f} MB.",
        )

    log.info("Standardizing '%s' for %s", file.filename, principal.email)
    raw_text = extract_raw_text(file_bytes, file.filename or "")

    if not raw_text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text could be read from this document. Scanned or image-only PDFs are not "
                   "supported -- please upload a text-based PDF or a DOCX.",
        )

    parsed_data = extract_resume_data(raw_text)
    parsed_data = repair_duplicated_achievements(parsed_data, raw_text)

    # Enforce single highest qualification
    if parsed_data.education:
        parsed_data.education = select_top_qualification(parsed_data.education)
        _warn_if_qualification_looks_missed(parsed_data.education[0], raw_text)

    payload = sanitize_resume_dict(parsed_data.model_dump())
    payload = restore_ampersands_from_source(payload, raw_text)

    document_bytes = render_resume(build_render_context(payload))

    base_name = Path(file.filename or "resume").stem
    download_filename = f"Standardized_{base_name}.docx"

    return Response(
        content=document_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{download_filename}"'},
    )
