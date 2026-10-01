"""Tests for qualification ranking.

The resume renders exactly one education entry, so picking the wrong tier is
immediately visible -- a senior candidate's resume showed "High School in
Science" because the hierarchy had MCA, BCA and Diploma in the wrong tiers.

Project hierarchy (deliberately not the academic convention for MCA/Diploma):
    10th < 12th/Intermediate/Diploma < BSc/BCA/BA/BCom/BBA
         < B.Tech/B.E/MCA < M.Tech/M.E/MBA < Doctorate/PhD
"""
import pytest

from src.utils import (
    TIER_BACHELORS_ENGINEERING,
    TIER_BACHELORS_GENERAL,
    TIER_DOCTORATE,
    TIER_INTERMEDIATE,
    TIER_MASTERS,
    TIER_SECONDARY,
    get_qualification_tier,
    highest_tier_in_text,
    rank_qualification,
    select_top_qualification,
)


@pytest.mark.parametrize(
    "degree,tier",
    [
        ("Ph.D in Computer Science", TIER_DOCTORATE),
        ("PhD", TIER_DOCTORATE),
        ("Doctor of Philosophy", TIER_DOCTORATE),
        ("M.Tech", TIER_MASTERS),
        ("M Tech Computer Science", TIER_MASTERS),
        ("MTech", TIER_MASTERS),
        ("M.E", TIER_MASTERS),
        ("MBA", TIER_MASTERS),
        ("M.Sc Physics", TIER_MASTERS),
        ("Master of Engineering", TIER_MASTERS),
        ("MCA", TIER_BACHELORS_ENGINEERING),
        ("B.Tech", TIER_BACHELORS_ENGINEERING),
        ("B.E", TIER_BACHELORS_ENGINEERING),
        ("Bachelor of Technology", TIER_BACHELORS_ENGINEERING),
        ("B.Sc", TIER_BACHELORS_GENERAL),
        ("BCA", TIER_BACHELORS_GENERAL),
        ("B.Com", TIER_BACHELORS_GENERAL),
        ("BBA", TIER_BACHELORS_GENERAL),
        ("B.A English", TIER_BACHELORS_GENERAL),
        ("Diploma in Electronics", TIER_INTERMEDIATE),
        ("Polytechnic", TIER_INTERMEDIATE),
        ("12th", TIER_INTERMEDIATE),
        ("Intermediate", TIER_INTERMEDIATE),
        ("Senior Secondary", TIER_INTERMEDIATE),
        ("Higher Secondary", TIER_INTERMEDIATE),
        ("High School in Science", TIER_SECONDARY),
        ("10th", TIER_SECONDARY),
        ("Matriculation", TIER_SECONDARY),
        ("SSC", TIER_SECONDARY),
    ],
)
def test_qualification_tiers(degree, tier):
    assert get_qualification_tier(degree) == tier


def test_hierarchy_is_strictly_ordered():
    g = get_qualification_tier
    assert g("10th") < g("12th") < g("B.Sc") < g("B.Tech") < g("M.Tech") < g("Ph.D")


@pytest.mark.parametrize(
    "a,b",
    [("12th", "Diploma"), ("BCA", "B.Sc"), ("MCA", "B.Tech"), ("MBA", "M.Tech"),
     ("High School", "10th")],
)
def test_same_tier_pairs(a, b):
    assert get_qualification_tier(a) == get_qualification_tier(b)


def test_unrecognised_text_is_tier_zero():
    assert get_qualification_tier("Certified Scrum Master") == 0
    assert get_qualification_tier("") == 0
    assert get_qualification_tier(None) == 0


# ------------------------------------------------------- the reported bug
def test_degree_beats_school_qualification():
    """The reported defect: a B.Tech must outrank 'High School in Science'."""
    educations = [
        {"degree": "High School in Science", "institution": "Bishop Westcott Boys School", "score": "54%"},
        {"degree": "B.Tech", "institution": "XYZ College of Engineering", "score": "65%"},
    ]
    assert select_top_qualification(educations)[0]["degree"] == "B.Tech"


def test_highest_wins_from_a_full_list():
    educations = [
        {"degree": "10th", "institution": "A"},
        {"degree": "12th", "institution": "B"},
        {"degree": "B.Tech", "institution": "C"},
        {"degree": "M.Tech", "institution": "D"},
    ]
    assert select_top_qualification(educations)[0]["degree"] == "M.Tech"


def test_institution_name_cannot_change_the_tier():
    """'Boys School' in the institution must not demote a real degree."""
    entry = {"degree": "B.Tech", "institution": "Bishop Westcott Boys School"}
    assert rank_qualification(entry) == TIER_BACHELORS_ENGINEERING


def test_institution_is_used_when_degree_is_unhelpful():
    entry = {"degree": "Science", "institution": "M.Tech, IIT Delhi"}
    assert rank_qualification(entry) == TIER_MASTERS


def test_single_entry_is_returned():
    educations = [{"degree": "B.Tech"}, {"degree": "12th"}]
    assert len(select_top_qualification(educations)) == 1


def test_empty_list():
    assert select_top_qualification([]) == []


def test_ties_keep_the_first_entry():
    educations = [{"degree": "B.Tech", "institution": "First"},
                  {"degree": "B.E", "institution": "Second"}]
    assert select_top_qualification(educations)[0]["institution"] == "First"


def test_pydantic_models_are_supported():
    from src.app import EducationItem

    items = [EducationItem(degree="10th", institution="A"),
             EducationItem(degree="MBA", institution="B")]
    assert select_top_qualification(items)[0].degree == "MBA"


# ------------------------------------------------- extraction-miss detector
def test_source_text_scan_finds_the_highest_mention():
    text = "Education: 10th CBSE 2004, 12th 2006, B.Tech Information Technology 2010"
    assert highest_tier_in_text(text) == TIER_BACHELORS_ENGINEERING


def test_scan_returns_zero_for_text_without_qualifications():
    assert highest_tier_in_text("Worked on Azure data pipelines.") == 0


# --------------------------------------------- free-text false positives
@pytest.mark.parametrize(
    "text",
    [
        "Certified Scrum Master",
        "Master Data Management",
        "MS SQL Server 2005",
        "Responsible for backups, needs to be restored nightly",
        "MS Office and MS Excel",
        "Associate Lead",
    ],
)
def test_text_scan_ignores_prose_and_product_names(text):
    """Bare 'BE'/'MS'/'Master' in running text must not look like a degree."""
    assert highest_tier_in_text(text) == 0


@pytest.mark.parametrize(
    "degree,tier",
    [("B.E", TIER_BACHELORS_ENGINEERING), ("M.S Computer Science", TIER_MASTERS),
     ("B.A English", TIER_BACHELORS_GENERAL), ("MS", TIER_MASTERS)],
)
def test_bare_abbreviations_still_rank_in_a_degree_field(degree, tier):
    assert get_qualification_tier(degree) == tier


def test_masters_plural_ranks_but_scrum_master_does_not():
    assert get_qualification_tier("Masters in Computer Applications") == TIER_MASTERS
    assert get_qualification_tier("Certified Scrum Master") == 0


# ------------------------------------------- written-form normalisation
@pytest.mark.parametrize(
    "degree,tier",
    [
        # The form that caused the live defect: a space after the dot.
        ("B. Tech in Electronics & Communication", TIER_BACHELORS_ENGINEERING),
        ("B. Tech", TIER_BACHELORS_ENGINEERING),
        ("B Tech", TIER_BACHELORS_ENGINEERING),
        ("B.Tech", TIER_BACHELORS_ENGINEERING),
        ("BTech", TIER_BACHELORS_ENGINEERING),
        ("B. E.", TIER_BACHELORS_ENGINEERING),
        ("B. Sc", TIER_BACHELORS_GENERAL),
        ("B.A.", TIER_BACHELORS_GENERAL),
        ("M. Tech", TIER_MASTERS),
        ("M. S.", TIER_MASTERS),
        ("M. B. A.", TIER_MASTERS),
        ("M.B.A", TIER_MASTERS),
        ("Ph. D.", TIER_DOCTORATE),
    ],
)
def test_spaced_and_dotted_degree_forms(degree, tier):
    """Resumes write degrees every possible way; all must normalise alike."""
    assert get_qualification_tier(degree) == tier


def test_spaced_btech_beats_high_school():
    """End-to-end form of the reported defect, with the real resume's values."""
    educations = [
        {"degree": "B. Tech in Electronics & Communication",
         "institution": "Dr. MGR Deemed University", "score": "76%"},
        {"degree": "High School in Science",
         "institution": "Bishop Westcott Boys School", "score": "54%"},
    ]
    assert select_top_qualification(educations)[0]["degree"].startswith("B. Tech")


def test_source_scan_detects_a_spaced_btech():
    """The miss-detector must see 'B. Tech' too, or it cannot flag a drop."""
    text = "EDUCATION\nB. Tech in Electronics & Communication\nDr. MGR Deemed University"
    assert highest_tier_in_text(text) == TIER_BACHELORS_ENGINEERING
