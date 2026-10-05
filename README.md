# Enterprise Resume Builder (NEXA)

Converts unstructured PDF/DOCX CVs into an ATS-compliant, branded two-page Word
document via FastAPI, Streamlit and `docxtpl`.

---

## Architecture

* **Frontend** — Streamlit, gated by Microsoft Entra ID (Azure App Service Easy Auth).
* **Backend** — FastAPI: text extraction, LLM structuring, sanitisation, template rendering.
* **LLM** — a failover chain of OpenAI-compatible providers (see below).
* **Document engine** — `docxtpl` / Jinja2 over a tagged Word template.

### The generated document

| Page | Region | Content |
| --- | --- | --- |
| 1 | Left pane | Name, title, profile, skills, highest qualification, certifications |
| 1 | Right pane | Synthesised career highlights |
| 2 | Full width | Companies → projects (role, duration) → achievement bullets |

---

## Security model — read before deploying

Easy Auth validates the Entra token **at the platform edge** and injects the
verified principal as `X-MS-CLIENT-PRINCIPAL-*` request headers. The application
trusts those headers, which is only safe while the platform is the sole route in.

Two invariants enforce that:

1. **The backend binds to `127.0.0.1` only** (`startup.sh`) and port 8000 is not
   published by the Dockerfile or compose file. It is unreachable from outside
   the container.
2. **Only port 8501 is exposed**, and it sits behind Easy Auth.

Do not publish port 8000. Doing so would let anyone forge a principal header.

`ALLOW_ANONYMOUS_AUTH=true` disables the sign-in requirement entirely and exists
only for local development. It must be absent or `false` in every deployed
environment.

### Required Entra configuration

In the App Service → **Authentication** blade:

* Identity provider: **Microsoft**, using your Insight tenant.
* "Restrict access" → **Require authentication**.
* Unauthenticated requests → **HTTP 302 redirect to identity provider**.
* Token store: **enabled**.

Tenant-wide access ("anyone with the URL can sign in") is the default for a
single-tenant registration — every Insight account may sign in, and
`ALLOWED_EMAIL_DOMAINS` provides a second check inside the app.

---

## LLM providers and failover

Providers are tried in order; the first to respond wins, so an exhausted free
tier fails over automatically. Configure any subset in `.env`:

| Order | Provider | Notes |
| --- | --- | --- |
| 1 | HuggingFace router | Current primary. Free tier is rate limited and slow (~100 s/resume). |
| 2 | Groq | Free, very fast, daily token caps. |
| 3 | Google Gemini | Most generous free tier. **Trains on free-tier inputs.** |
| 4 | Cerebras | Free tier. |
| 5 | Azure OpenAI | No training on your data, Entra-native. The enterprise option. |

Override the order with `LLM_PROVIDER_ORDER=gemini,huggingface`.

> **PII warning.** Resumes are candidate personal data. The free tiers of Gemini
> (and most others) reserve the right to train on submitted content. For real
> candidate data, use Azure OpenAI or a paid tier.

---

## Running locally

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt

copy .env.example .env        # then fill in at least one provider key
# For local use, set ALLOW_ANONYMOUS_AUTH=true
```

**Terminal 1 — backend**

```bash
python -m uvicorn src.app:app --host 127.0.0.1 --port 8000 --reload
```

* Docs: <http://127.0.0.1:8000/docs>
* Health: <http://127.0.0.1:8000/health> — also reports the template contract and
  the active provider chain.

**Terminal 2 — UI**

```bash
python -m streamlit run src/ui.py --server.port 8501 --server.address 127.0.0.1
```

Bind the UI to `127.0.0.1` locally. With `ALLOW_ANONYMOUS_AUTH=true` the sign-in
gate is off, so `0.0.0.0` would expose an unauthenticated app to your network.

### Tests

```bash
python -m pytest tests/ -q
```

---

## The template contract

The Word template uses short tag names (`{{ name }}`, `{{ title }}`,
`{{ profile }}`, `{{ edu.institution_line }}`) that deliberately differ from the
extraction schema (`full_name`, `headline`, …). `build_render_context()` in
[src/app.py](src/app.py) is the single mapping point between the two.

Two guards keep them in sync:

* Rendering uses `StrictUndefined`, so a mismatch raises instead of silently
  emitting a blank field.
* `GET /health` reports `template_contract.unsatisfied` — any template tag the
  code does not supply.

If you edit the template in Word and add a tag, add it to `TEMPLATE_VARIABLES`
and to `build_render_context()`, then run the tests.

> Rendering sets `autoescape=True`. `docxtpl` defaults it to `False`, which
> injects raw `&`, `<` and `>` into `document.xml` and silently corrupts output —
> literal ampersands in `Data & AI` simply disappear. Do not turn it off.

---

## Two-page layout

The document is exactly two pages, and both halves are enforced in code rather
than left to chance.

**Page 1** is a single-row, two-cell table. If the left cell outgrows the page,
Word splits the row across the page boundary and the pane bleeds alongside the
right pane. `MAX_SKILLS`, `MAX_CERTIFICATIONS` and `PROFILE_MAX_WORDS` keep it
within one page.

**Page 2** holds PROFESSIONAL EXPERIENCE, which starts on a hard page break. One
block per employer:

```text
Insight Direct                                        Jan 2023 - Present
Practice Manager - Data
• Boosted revenue by 20% by spearheading a Data managed services practice.
• Directed a team of thirteen data engineers, improving throughput by 30%.
```

Company name and tenure share a line, the dates pushed right by a right-aligned
tab stop at the margin; the job title sits beneath in a smaller bold face.

The schema is **flat — one entry per employer, no nested projects.** An earlier
version nested projects, but the model filled each project's client with the
company name and its role with a sentence of responsibilities, rendering a
duplicate heading (`Client / Project: Insight Direct - Practice Manager - Data`)
directly under the company line. Matching the schema to the rendered layout
removed that failure mode outright.

Only the **most recent `MAX_COMPANIES` employers (default 3)** are shown. A
twenty-year career lists early jobs whose detail has stopped mattering, and the
reclaimed space buys five full achievements for the roles that do. Raise
`MAX_COMPANIES` to show more history.

The job title is the **latest role at that employer**, not the most senior or
the last one printed. Where a CV lists a "Growth Path", the model is given a
worked example so it picks the role with the most recent dates — a career
running `… Lead - Service Improvement (Aug'13-Sep'13), Consultant - TechOps IT
(Dec'13-Mar'15)` must render as *Consultant - TechOps IT*.

`fit_experience_to_page()` then trims achievements per company — 5, then 4, 3,
2 — until the section fits `EXPERIENCE_LINE_BUDGET`. **Every employer shown
keeps its heading**; only bullets give way. If even the last step overflows the
content is kept and a third page allowed, with a warning logged.

Achievements are de-duplicated **globally, not per company** — models reuse a
generic bullet under two employers, and the same sentence twice on one page
reads as carelessness. Remaining bullets are ranked so quantified, high-impact
ones survive trimming.

The budget is **calibrated against Word, not derived from page geometry**: with
page 1 maximally filled, page 2 holds **40 lines; 44 spills to a third page**.
Measured at both extremes — single-line bullets, where the estimate equals the
real line count, and long wrapped ones.

`EXPERIENCE_CHARS_PER_LINE` (85) is deliberately below the true ~90-character
wrap width, so the estimate over-counts wrapped text. That margin is what makes
a budget of exactly 40 safe. Re-measure after any template or font change:

```bash
python tools/page_count.py <rendered>.docx
```

`title` and `profile` are normalised too: the headline is reduced to the job
title alone ("Data Engineering Manager", not "…with over 17 years of
experience"), and the profile is trimmed to `PROFILE_MAX_WORDS` on a sentence
boundary.

> The control tags in the template are docxtpl **paragraph** tags (`{%p ... %}`),
> not inline `{% ... %}`. Inline tags leave an empty paragraph behind for every
> loop iteration — they previously accounted for 59 of 103 paragraphs and were
> the main cause of overflow. If you edit the template in Word, keep the `p`.

Verify any layout change against a real renderer, since python-docx has no
concept of pages:

```bash
pip install pywin32                      # Windows + Word, dev only
python tools/page_count.py out.docx
```

---

## Known limitations

* **Legacy `.doc` is not supported.** `python-docx` reads OOXML only. The upload
  form accepts `.docx` and `.pdf`; `.doc` files must be re-saved in Word. Adding
  real `.doc` support means installing LibreOffice in the image (~400 MB).
* **Scanned/image-only PDFs** yield no text; there is no OCR fallback.
* **"Create your Resume" is not wired up.** The form is a preview: entries are
  not persisted and cannot be compiled. Per-company and per-project date pickers
  and skill/certification pickers are the next milestone.
* Only the single highest qualification is rendered, by design
  ([src/utils.py](src/utils.py)). The hierarchy is project-specific, not the
  academic convention — **MCA ranks with the engineering bachelors and Diploma
  with 12th**:

  ```text
  10th < 12th / Intermediate / Diploma < BSc / BCA / BA / BCom / BBA
       < B.Tech / B.E / MCA < M.Tech / M.E / MBA < Doctorate / PhD
  ```

  Ranking reads the `degree` field first so an institution name cannot demote a
  real degree ("B.Tech" at a "Boys School" is still a bachelors). Bare
  two-letter abbreviations (`BE`, `MS`, `MA`) are only honoured in a degree
  field, never when scanning resume prose, where they mean "be" and "MS SQL".
  If the source text mentions a higher qualification than the one extracted, a
  warning is logged — the model dropped it, and inventing an institution to
  replace it would be worse.

---

## Project structure

```text
├── Dockerfile
├── requirements.txt
├── startup.sh
├── .env.example
├── prod/docker-compose.yml
├── src/
│   ├── app.py          # FastAPI backend
│   ├── ui.py           # Streamlit UI + auth gate
│   ├── auth.py         # Entra / Easy Auth principal extraction
│   ├── llm.py          # Provider failover chain
│   ├── config.py       # .env loading (import before module-level getenv)
│   ├── utils.py        # Qualification ranking
│   └── templates/ResumeTemplate_Tagged.docx
└── tests/
```
