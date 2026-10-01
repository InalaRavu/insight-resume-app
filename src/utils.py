"""Qualification ranking.

The resume shows a single education entry: the candidate's highest
qualification. This module decides which that is.

The hierarchy is the one specified for this project:

    10th  <  12th / Intermediate / Diploma  <  BSc / BCA / BA / BCom / BBA
          <  B.Tech / B.E / MCA  <  M.Tech / M.E / MBA  <  Doctorate / PhD

Two tiers are deliberately not the academic convention: MCA sits with the
engineering bachelors rather than the masters, and Diploma sits with 12th.

Matching runs on a normalised form (uppercased, periods and spaces removed from
abbreviations) because degrees arrive as "M.Tech", "M Tech", "MTech" and
"M.TECH" interchangeably. Tiers are checked highest-first, so a longer phrase
("Senior Secondary") is always tested before the shorter one it contains
("Secondary").
"""
import re
from typing import Any, List, Optional, Tuple

# Tier values are spaced so callers can compare them numerically; 0 = unknown.
TIER_DOCTORATE = 60
TIER_MASTERS = 50
TIER_BACHELORS_ENGINEERING = 40
TIER_BACHELORS_GENERAL = 30
TIER_INTERMEDIATE = 20
TIER_SECONDARY = 10
TIER_UNKNOWN = 0

TIER_NAMES = {
    TIER_DOCTORATE: "Doctorate",
    TIER_MASTERS: "Masters",
    TIER_BACHELORS_ENGINEERING: "Bachelors (Engineering) / MCA",
    TIER_BACHELORS_GENERAL: "Bachelors (General)",
    TIER_INTERMEDIATE: "12th / Intermediate / Diploma",
    TIER_SECONDARY: "10th / Matriculation",
    TIER_UNKNOWN: "Unknown",
}

# Each entry: (tier, unambiguous alternatives, ambiguous alternatives).
# Order matters -- highest tier first.
#
# The ambiguous column holds bare two-letter abbreviations. In a degree field
# "BE" means B.E., but in running prose it is the verb "be"; likewise "MS" is a
# degree in one place and "MS SQL Server" in another. They are therefore matched
# only against a known degree field, never when scanning whole-resume text.
#
# Singular "Master"/"Bachelor" are excluded on purpose: "Certified Scrum Master"
# is not a postgraduate degree. The plural, or "Master of <subject>", is.
_TIER_PATTERNS: List[Tuple[int, List[str], List[str]]] = [
    (TIER_DOCTORATE, [
        r"PHD", r"PH D", r"DPHIL", r"DOCTORATE", r"DOCTORAL", r"POSTDOC",
        r"POST DOCTORAL", r"DSC", r"DLITT", r"DOCTOR OF \w+",
    ], []),
    (TIER_MASTERS, [
        r"MTECH", r"MENGG?", r"MSC", r"MBA", r"MCOM", r"MSW", r"MPHIL", r"MPH",
        r"LLM", r"PGDM", r"PGDBM", r"PGDBA", r"MASTERS",
        r"MASTER OF \w+", r"MASTERS? IN \w+", r"POST ?GRADUATE", r"POSTGRADUATION",
    ], [r"ME", r"MS", r"MA"]),
    (TIER_BACHELORS_ENGINEERING, [
        # MCA is placed here by project convention, not academic convention.
        r"BTECH", r"BENGG?", r"MCA",
        r"BACHELOR OF TECHNOLOGY", r"BACHELOR OF ENGINEERING",
    ], [r"BE"]),
    (TIER_BACHELORS_GENERAL, [
        r"BSC", r"BCA", r"BCOM", r"BBA", r"BBM", r"BMS", r"BPHARM", r"LLB",
        r"BACHELORS", r"BACHELOR OF \w+", r"BACHELORS? IN \w+", r"UNDER ?GRADUATE",
    ], [r"BA"]),
    (TIER_INTERMEDIATE, [
        r"12TH", r"XII", r"INTERMEDIATE", r"HSC", r"SENIOR SECONDARY",
        r"HIGHER SECONDARY", r"DIPLOMA", r"POLYTECHNIC", r"PUC",
        r"PRE ?UNIVERSITY", r"ASSOCIATE DEGREE", r"PLUS TWO",
    ], []),
    (TIER_SECONDARY, [
        # "High School" is 10th in the Indian system this template targets.
        r"10TH", r"MATRICULATION", r"MATRIC", r"SSC", r"SECONDARY",
        r"HIGH SCHOOL", r"CBSE", r"ICSE", r"SSLC",
    ], []),
]


def _compile(include_ambiguous: bool) -> List[Tuple[int, re.Pattern]]:
    compiled = []
    for tier, strict, ambiguous in _TIER_PATTERNS:
        alts = strict + (ambiguous if include_ambiguous else [])
        if alts:
            compiled.append((tier, re.compile(r"\b(?:" + "|".join(alts) + r")\b")))
    return compiled


# For a known degree field, where a bare abbreviation is almost certainly a degree.
_COMPILED_FULL = _compile(include_ambiguous=True)
# For scanning free text, where it almost certainly is not.
_COMPILED_STRICT = _compile(include_ambiguous=False)


def _normalise(text: str) -> str:
    """Uppercase and fold abbreviation punctuation so 'M.Tech' == 'MTECH'.

    Periods and internal spaces are removed only between single letters and a
    following token, which keeps 'M.Tech'/'M Tech' collapsing to 'MTECH' while
    leaving real words ('Master of Science') intact.
    """
    text = text.upper()
    text = text.replace("&", " AND ")
    # Fold dots inside abbreviations: "PH.D" -> "PHD", "M.TECH" -> "MTECH".
    # Only dots flanked by letters are removed, so a dot ending a sentence still
    # becomes a separator and cannot fuse two unrelated words.
    text = re.sub(r"(?<=[A-Z])\.(?=[A-Z])", "", text)
    # Punctuation becomes whitespace BEFORE the prefix collapse below, so that
    # "B. Tech" (dot *and* space, as real resumes write it) reaches that rule as
    # "B TECH". Collapsing first would leave "B. TECH" unmatched -- which is how
    # a genuine B.Tech once scored zero and lost to a high-school entry.
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Join a whole run of separated single letters at once: "M B A" -> "MBA".
    # Matching the entire run matters -- collapsing pairwise left to right would
    # turn "M B A" into "MB A" and then stop, because "MB" is no longer a single
    # letter. Multi-letter words are untouched, so "B TECH" survives for the
    # rule below.
    text = re.sub(
        r"\b(?:[A-Z]\s+)+[A-Z]\b",
        lambda m: m.group(0).replace(" ", ""),
        text,
    )
    # Collapse a single-letter prefix written separately: "B TECH" -> "BTECH".
    text = re.sub(
        r"\b([A-Z])\s+(TECH|SC|COM|PHIL|ENGG?|PHARM|ED|SW)\b", r"\1\2", text
    )
    return text


def get_qualification_tier(text: Optional[str], strict: bool = False) -> int:
    """Return the tier constant for a qualification string, 0 if unrecognised.

    strict=True drops bare two-letter abbreviations, for use on free text where
    "BE" and "MS" are far more likely to be prose than degrees.
    """
    if not text:
        return TIER_UNKNOWN
    normalised = _normalise(text)
    for tier, pattern in (_COMPILED_STRICT if strict else _COMPILED_FULL):
        if pattern.search(normalised):
            return tier
    return TIER_UNKNOWN


# Retained for backwards compatibility with earlier callers.
get_qualification_weight = get_qualification_tier


def _entry_fields(item: Any) -> Tuple[str, str]:
    """Return (degree, supporting_text) for a pydantic model, dict or string."""
    if hasattr(item, "degree"):
        degree = getattr(item, "degree", "") or ""
        extra = f"{getattr(item, 'title', '') or ''} {getattr(item, 'institution', '') or ''}"
    elif isinstance(item, dict):
        degree = item.get("degree", "") or ""
        extra = f"{item.get('title', '') or ''} {item.get('institution', '') or ''}"
    else:
        degree, extra = str(item), ""
    return degree, extra


def rank_qualification(item: Any) -> int:
    """Tier an education entry, preferring its degree field.

    The degree is checked alone first so an institution name cannot influence
    the result -- "Bishop Westcott Boys School" must not make a B.Tech look like
    a school qualification.
    """
    degree, extra = _entry_fields(item)
    tier = get_qualification_tier(degree)
    if tier != TIER_UNKNOWN:
        return tier
    return get_qualification_tier(f"{degree} {extra}")


def select_top_qualification(educations: List[Any]) -> List[Any]:
    """Return a single-entry list holding the highest qualification.

    Ties keep the earlier entry, since resumes list education newest-first.
    """
    if not educations:
        return []
    ranked = [(rank_qualification(item), idx, item) for idx, item in enumerate(educations)]
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [ranked[0][2]]


def highest_tier_in_text(text: Optional[str]) -> int:
    """Highest qualification tier mentioned anywhere in a block of text.

    Used to detect extraction misses: if the source resume mentions a degree but
    only a school qualification was extracted, that is worth flagging.
    """
    return get_qualification_tier(text, strict=True)
