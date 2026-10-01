"""Tests for page-fitting: headline, profile and experience condensation.

The document must be exactly two pages: page 1 carries both panes, page 2
carries PROFESSIONAL EXPERIENCE in full. These cover the content-volume rules
that keep it there.
"""
import os

import pytest

os.environ.setdefault("ALLOW_ANONYMOUS_AUTH", "true")

from src.app import (  # noqa: E402
    EXPERIENCE_LINE_BUDGET,
    MAX_CERTIFICATIONS,
    MAX_SKILLS,
    PROFILE_MAX_WORDS,
    _clean_job_title,
    _dedupe_bullets,
    _estimate_experience_lines,
    _prepare_companies,
    _select_significant,
    _trim_profile,
    build_render_context,
    fit_experience_to_page,
)


# --------------------------------------------------------------- job title
@pytest.mark.parametrize(
    "headline,expected",
    [
        ("Data Engineering Manager with over 17 years of experience", "Data Engineering Manager"),
        ("Lead Architect, over 12 years building platforms", "Lead Architect"),
        ("Senior Data & AI Architect | Gurugram, India", "Senior Data & AI Architect"),
        ("Practice Manager - Data", "Practice Manager - Data"),
        ("Engineering Manager having 9 years of delivery experience", "Engineering Manager"),
        ("Solutions Architect (15+ years)", "Solutions Architect"),
        ("", ""),
        (None, ""),
    ],
)
def test_clean_job_title(headline, expected):
    assert _clean_job_title(headline) == expected


def test_job_title_keeps_ampersands():
    assert "&" in _clean_job_title("Head of Data & Analytics with 20 years")


def test_job_title_caps_runaway_length():
    long_title = " ".join(["Word"] * 20)
    assert len(_clean_job_title(long_title).split()) <= 8


# ----------------------------------------------------------------- profile
def test_profile_trimmed_to_word_budget():
    long_profile = ". ".join(f"Sentence number {i} with several filler words here" for i in range(20))
    assert len(_trim_profile(long_profile).split()) <= PROFILE_MAX_WORDS


def test_short_profile_is_left_alone():
    short = "Data architect with a decade of cloud platform delivery."
    assert _trim_profile(short) == short


def test_profile_cuts_on_a_sentence_boundary():
    profile = ("First sentence is short. " + " ".join(["padding"] * 80) + ". Third sentence.")
    result = _trim_profile(profile)
    assert result.startswith("First sentence is short.")


def test_single_overlong_sentence_is_still_truncated():
    """No sentence boundary to cut on -- must fall back to a word cut."""
    runaway = " ".join(["word"] * 200)
    result = _trim_profile(runaway)
    assert len(result.split()) <= PROFILE_MAX_WORDS
    assert result.endswith(".")


# ------------------------------------------------------------- page fitting
def _company(name, n_bullets, bullet_len=80):
    return {
        "company_name": name,
        "overall_title": "Engineering Manager",
        "duration": "2019 - 2023",
        "achievements": [f"{name}-b{b} " + "x" * bullet_len for b in range(n_bullets)],
    }


def test_small_history_keeps_every_achievement():
    companies = _prepare_companies([_company("Acme", 3, bullet_len=40)])
    fitted = fit_experience_to_page(companies)
    assert len(fitted[0]["achievements"]) == 3


def test_large_history_is_trimmed_within_budget():
    companies = _prepare_companies([_company(f"Co{i}", 5, bullet_len=120) for i in range(6)])
    assert _estimate_experience_lines(companies) > EXPERIENCE_LINE_BUDGET
    fitted = fit_experience_to_page(companies)
    assert _estimate_experience_lines(fitted) <= EXPERIENCE_LINE_BUDGET


def test_trimming_never_drops_a_company():
    """The one invariant: every employer survives, however tight the budget."""
    raw = [_company(f"Co{i}", 5, bullet_len=160) for i in range(10)]
    companies = _prepare_companies(raw)
    fitted = fit_experience_to_page(companies)
    assert len(fitted) == len(raw)
    for original, result in zip(companies, fitted):
        assert result["company_name"] == original["company_name"]
        assert result["role"] == original["role"]
        assert result["duration"] == original["duration"]


def test_company_keeps_at_most_the_configured_ceiling():
    from src.app import COMPANY_BULLET_STEPS

    ceiling = max(COMPANY_BULLET_STEPS)
    companies = _prepare_companies([_company(f"Co{i}", 12) for i in range(4)])
    for comp in fit_experience_to_page(companies):
        assert len(comp["achievements"]) <= ceiling


def test_duplicate_achievements_are_removed_on_prepare():
    raw = [{
        "company_name": "Kantar", "overall_title": "Engineering Manager", "duration": "2019 - 2023",
        "achievements": ["Architected Datawarehouse and designed ETL pipelines.",
                         "architected  datawarehouse and designed ETL pipelines",
                         "Built a Datalake."],
    }]
    assert len(_prepare_companies(raw)[0]["achievements"]) == 2


def test_role_comes_from_the_job_title_not_a_sentence():
    raw = [{"company_name": "Insight Direct", "overall_title": "Practice Manager - Data",
            "duration": "Jan 2023 - Present", "achievements": ["Boosted revenue by 20%."]}]
    prepared = _prepare_companies(raw)
    assert prepared[0]["role"] == "Practice Manager - Data"
    assert prepared[0]["company_name"] == "Insight Direct"


def test_empty_history_is_handled():
    assert fit_experience_to_page([]) == []


# ------------------------------------------------------- bullet selection
def test_duplicate_bullets_are_removed():
    bullets = ["Architected the warehouse.", "architected the  warehouse", "Built pipelines."]
    assert len(_dedupe_bullets(bullets)) == 2


def test_quantified_achievements_are_preferred():
    bullets = [
        "Responsible for routine maintenance tasks.",
        "Attended meetings and took notes.",
        "Boosted revenue by 20% across the practice.",
    ]
    assert "Boosted revenue by 20% across the practice." in _select_significant(bullets, 1)


def test_selection_preserves_original_order():
    bullets = ["Reduced cost by 10%.", "Did some filler work.", "Increased uptime by 30%."]
    chosen = _select_significant(bullets, 2)
    assert chosen == ["Reduced cost by 10%.", "Increased uptime by 30%."]


def test_selection_is_a_noop_below_the_limit():
    bullets = ["One.", "Two."]
    assert _select_significant(bullets, 6) == bullets


# ------------------------------------------------------------ pane budgets
def test_extraction_prompt_formats_with_all_placeholders():
    """A KeyError here would break every request, so assert it builds.

    Calls the production builder rather than re-listing the arguments, so adding
    a placeholder cannot pass the test while breaking the app.
    """
    from src.app import MAX_ACHIEVEMENTS_PER_COMPANY, build_extraction_prompt

    prompt = build_extraction_prompt()
    assert "{max_" not in prompt and "{schema" not in prompt
    assert str(MAX_ACHIEVEMENTS_PER_COMPANY) in prompt
    assert str(MAX_CERTIFICATIONS) in prompt


def test_achievements_are_capped_by_the_sanitiser():
    from src.app import MAX_ACHIEVEMENTS_PER_COMPANY, sanitize_resume_dict

    data = {
        "work_experience": [
            {"company_name": "X", "overall_title": "Y", "duration": "Z",
             "achievements": [f"Bullet {i}" for i in range(12)]}
        ]
    }
    cleaned = sanitize_resume_dict(data)
    kept = cleaned["work_experience"][0]["achievements"]
    assert len(kept) == MAX_ACHIEVEMENTS_PER_COMPANY


def test_left_pane_lists_are_capped():
    ctx = build_render_context({
        "full_name": "A B",
        "headline": "Engineer",
        "profile_summary": "Short profile.",
        "skills": [f"Skill{i}" for i in range(40)],
        "certifications": [f"Cert{i}" for i in range(40)],
    })
    assert len(ctx["skills"]) == MAX_SKILLS
    assert len(ctx["certifications"]) == MAX_CERTIFICATIONS


def test_duplicate_achievements_removed_across_companies():
    """Models reuse a generic bullet under two employers; the first keeps it."""
    shared = "Played a key role in developing a data governance framework."
    raw = [
        {"company_name": "Kantar", "overall_title": "Engineering Manager",
         "duration": "2019 - 2023", "achievements": [shared, "Migrated legacy systems."]},
        {"company_name": "BI Worldwide", "overall_title": "Associate Lead",
         "duration": "2013 - 2019", "achievements": [shared, "Built Power BI dashboards."]},
    ]
    prepared = _prepare_companies(raw)
    assert shared in prepared[0]["achievements"]
    assert shared not in prepared[1]["achievements"]
    assert "Built Power BI dashboards." in prepared[1]["achievements"]


def test_only_the_most_recent_companies_are_shown():
    """Older employers are dropped, not compressed."""
    from src.app import MAX_COMPANIES

    raw = [
        {"company_name": f"Employer {i}", "overall_title": "Engineer",
         "duration": f"20{10+i} - 20{11+i}", "achievements": [f"Did thing {i}."]}
        for i in range(8)
    ]
    ctx = build_render_context({"full_name": "A B", "work_experience": raw})
    shown = [c["company_name"] for c in ctx["work_experience"]]
    assert len(shown) == MAX_COMPANIES
    # The model is told to list most recent first, so the cap takes the head.
    assert shown == [f"Employer {i}" for i in range(MAX_COMPANIES)]


def test_fewer_companies_than_the_cap_are_all_kept():
    raw = [{"company_name": "Only One", "overall_title": "Engineer",
            "duration": "2020 - 2024", "achievements": ["Did a thing."]}]
    ctx = build_render_context({"full_name": "A B", "work_experience": raw})
    assert len(ctx["work_experience"]) == 1


def test_company_emptied_by_dedupe_is_dropped_not_left_bare():
    """Regression: the model copied one employer's bullets onto another.

    De-duplication correctly stripped the copies, but left a heading with no
    achievements under it. The employer is dropped so the next one is shown.
    """
    shared = [f"Migrated {i} platforms to Databricks Unity Catalog." for i in range(3)]
    raw = [
        {"company_name": "Insight Direct", "overall_title": "Architect",
         "duration": "2024 - Present", "achievements": list(shared)},
        {"company_name": "Wipro Ltd.", "overall_title": "Consultant - TechOps IT",
         "duration": "2007 - 2015", "achievements": list(shared)},   # verbatim copy
        {"company_name": "Brigade Corporation", "overall_title": "SME",
         "duration": "2006 - 2007", "achievements": ["Supported HP Notebooks."]},
    ]
    prepared = _prepare_companies(raw)
    names = [c["company_name"] for c in prepared]
    assert "Wipro Ltd." not in names
    assert names == ["Insight Direct", "Brigade Corporation"]
    assert all(c["achievements"] for c in prepared)


def test_partial_duplication_keeps_the_company():
    """Only a wholesale copy drops an employer; partial overlap is trimmed."""
    raw = [
        {"company_name": "A", "overall_title": "Architect", "duration": "2024 - Present",
         "achievements": ["Shared bullet.", "Unique to A."]},
        {"company_name": "B", "overall_title": "Consultant", "duration": "2007 - 2015",
         "achievements": ["Shared bullet.", "Unique to B."]},
    ]
    prepared = _prepare_companies(raw)
    assert [c["company_name"] for c in prepared] == ["A", "B"]
    assert prepared[1]["achievements"] == ["Unique to B."]


# ------------------------------------------------- duplicated-employer repair
def _resume_with_copied_bullets():
    from src.app import ResumeData, WorkHistory

    shared = [f"Migrated {i} platforms to Databricks Unity Catalog." for i in range(3)]
    return ResumeData(
        full_name="Ravi Inala", headline="Architect", profile_summary="x",
        work_experience=[
            WorkHistory(company_name="Insight Direct", overall_title="Architect",
                        duration="2024 - Present", achievements=list(shared)),
            WorkHistory(company_name="Wipro Ltd.", overall_title="Consultant - TechOps IT",
                        duration="2007 - 2015", achievements=list(shared)),
        ],
    )


def test_wholesale_copy_triggers_targeted_reextraction(monkeypatch):
    import src.app as app

    calls = []

    def fake_reextract(company, raw_text):
        calls.append(company.company_name)
        return ["Managed incident and change processes for British Telecom."]

    monkeypatch.setattr(app, "_reextract_company_achievements", fake_reextract)
    repaired = app.repair_duplicated_achievements(_resume_with_copied_bullets(), "resume text")

    assert calls == ["Wipro Ltd."]            # only the copying employer
    assert repaired.work_experience[1].achievements == [
        "Managed incident and change processes for British Telecom."
    ]
    assert len(repaired.work_experience[0].achievements) == 3   # original untouched


def test_failed_reextraction_leaves_no_fabricated_bullets(monkeypatch):
    """If the repair fails, the copied bullets must not survive."""
    import src.app as app

    monkeypatch.setattr(app, "_reextract_company_achievements", lambda c, t: [])
    repaired = app.repair_duplicated_achievements(_resume_with_copied_bullets(), "resume text")
    assert repaired.work_experience[1].achievements == []


def test_distinct_achievements_are_not_reextracted(monkeypatch):
    import src.app as app
    from src.app import ResumeData, WorkHistory

    called = []
    monkeypatch.setattr(app, "_reextract_company_achievements",
                        lambda c, t: called.append(c.company_name) or [])
    data = ResumeData(
        full_name="A", headline="B", profile_summary="c",
        work_experience=[
            WorkHistory(company_name="A Ltd", overall_title="X", duration="d", achievements=["One."]),
            WorkHistory(company_name="B Ltd", overall_title="Y", duration="e", achievements=["Two."]),
        ],
    )
    app.repair_duplicated_achievements(data, "text")
    assert called == []


def test_partial_overlap_is_not_treated_as_a_copy(monkeypatch):
    import src.app as app
    from src.app import ResumeData, WorkHistory

    called = []
    monkeypatch.setattr(app, "_reextract_company_achievements",
                        lambda c, t: called.append(c.company_name) or [])
    data = ResumeData(
        full_name="A", headline="B", profile_summary="c",
        work_experience=[
            WorkHistory(company_name="A Ltd", overall_title="X", duration="d",
                        achievements=["Shared.", "Unique A."]),
            WorkHistory(company_name="B Ltd", overall_title="Y", duration="e",
                        achievements=["Shared.", "Unique B."]),
        ],
    )
    app.repair_duplicated_achievements(data, "text")
    assert called == []


def test_json_array_extraction():
    from src.app import _extract_json_array

    assert _extract_json_array('```json\n["a", "b"]\n```') == '["a", "b"]'
    assert _extract_json_array('Here you go: ["a"] thanks') == '["a"]'
    assert _extract_json_array('["a ] bracket"]') == '["a ] bracket"]'
    assert _extract_json_array('no array here') == '[]'
