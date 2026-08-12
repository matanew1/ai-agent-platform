"""Local tool simulating how an Applicant Tracking System (ATS) reads a resume.

Pure text analysis, no external ATS account/API - the same "no external
paid dependency" call this module already made for Markdown stripping (see
``markdown.py``'s docstring on regex vs. a parsing dependency). Real ATS
products (Workday, Greenhouse, Taleo, iCIMS, ...) don't expose a public
parsing API to test against; this approximates the well-documented class of
problems they share (missing standard sections, no machine-readable contact
info, dense unstructured paragraphs, poor keyword overlap with the target
role) rather than replicating any one vendor exactly.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from shared.types import ToolDefinition

logger = logging.getLogger(__name__)

DEFINITION = ToolDefinition(
    name="analyze_ats_compatibility",
    description=(
        "Analyze resume/CV text the way an Applicant Tracking System (ATS) would: detect "
        "standard sections (Experience, Education, Skills, ...), verify machine-readable "
        "contact info, flag formatting that ATS parsers commonly mishandle, and - when a "
        "target job_description is supplied - score keyword overlap against it. Use this "
        "when the user asks whether their CV/resume will pass ATS screening, wants an ATS "
        "compatibility score, or wants to tailor a resume to a specific job posting. "
        "Returns a structured report with a 0-100 score, missing sections, formatting "
        "issues, and matched/missing keywords."
    ),
    parameters={
        "type": "object",
        "properties": {
            "resume_text": {
                "type": "string",
                "description": "The resume/CV content to analyze, as plain text.",
            },
            "job_description": {
                "type": "string",
                "description": (
                    "Optional target job posting text. When given, the report includes a "
                    "keyword-overlap score and the posting's significant terms missing from "
                    "the resume."
                ),
            },
        },
        "required": ["resume_text"],
    },
)

# Canonical section -> header patterns an ATS's section-splitter looks for.
# Matched against short, mostly-alone lines (see _find_sections) rather than
# anywhere in running text, so "my professional experience includes..." in a
# summary paragraph doesn't count as an Experience *header*.
_SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "Contact": re.compile(r"^(contact( info(rmation)?)?)$", re.IGNORECASE),
    "Summary": re.compile(r"^(summary|profile|objective|about( me)?)$", re.IGNORECASE),
    "Experience": re.compile(
        r"^(work )?(experience|employment( history)?|professional experience)$", re.IGNORECASE
    ),
    "Education": re.compile(r"^education( and training)?$", re.IGNORECASE),
    "Skills": re.compile(
        r"^(skills|technical skills|core competencies|areas of expertise)$", re.IGNORECASE
    ),
    "Certifications": re.compile(r"^(certifications?|licenses?)$", re.IGNORECASE),
    "Projects": re.compile(r"^projects?$", re.IGNORECASE),
}
# What most ATS section-parsers expect to find at minimum - Contact/
# Certifications/Projects are common but not universal, so they're detected
# and reported when present without being counted as "missing" when absent.
_EXPECTED_SECTIONS = ("Summary", "Experience", "Education", "Skills")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Loose on purpose - resumes format phone numbers wildly (dashes, dots,
# spaces, parens, country codes); this only needs to catch "something
# phone-shaped exists", not validate it.
_PHONE = re.compile(r"(\+?\d[\d\-.\s()]{7,}\d)")

_STOPWORDS = frozenset(
    """
    a an the and or but if to of in on for with at by from as is are was were
    be been being this that these those it its your you we our they their
    will shall can may must should would could not no nor do does did have
    has had into out about over under between per than then so such
    """.split()
)
_WORD = re.compile(r"[a-zA-Z][a-zA-Z+.#-]{1,}")

# Dense-paragraph heuristic: a "line" this long with no bullet/newline
# structure is the plain-text signature of a formatted block (table cell,
# multi-column layout, or an unbroken wall of prose) that many ATS parsers
# either garble or dump out of order - we only see the text, not the
# original layout, so this is the closest proxy available.
_LONG_UNSTRUCTURED_LINE_CHARS = 400
_MAX_REPORTED_MISSING_KEYWORDS = 15


def _find_sections(text: str) -> tuple[list[str], list[str]]:
    """Return (sections_found, sections_missing) against short candidate lines."""
    found: list[str] = []
    for line in text.splitlines():
        candidate = line.strip().strip(":").strip()
        if not candidate or len(candidate) > 40:
            continue
        for name, pattern in _SECTION_PATTERNS.items():
            if name not in found and pattern.match(candidate):
                found.append(name)
    missing = [name for name in _EXPECTED_SECTIONS if name not in found]
    return found, missing


def _find_formatting_issues(text: str) -> list[str]:
    issues: list[str] = []
    lines = [line for line in text.splitlines() if line.strip()]

    if not _EMAIL.search(text):
        issues.append("No email address detected - ATS contact fields may be left blank.")
    if not _PHONE.search(text):
        issues.append("No phone number detected - ATS contact fields may be left blank.")

    long_lines = [line for line in lines if len(line) > _LONG_UNSTRUCTURED_LINE_CHARS]
    if long_lines:
        issues.append(
            f"{len(long_lines)} very long unbroken line(s) detected - often the plain-text "
            "signature of a table or multi-column layout, which many ATS parsers garble or "
            "read out of order. Prefer a single-column layout with short bullet points."
        )

    bullet_lines = sum(1 for line in lines if line.lstrip()[:1] in ("-", "*", "•"))
    if lines and bullet_lines / len(lines) < 0.15:
        issues.append(
            "Few bulleted lines detected - ATS-friendly resumes typically use short bullet "
            "points for experience/skills rather than dense paragraphs."
        )

    word_count = len(_WORD.findall(text))
    if word_count < 150:
        issues.append(
            f"Only ~{word_count} words - likely too short to give an ATS keyword matcher "
            "enough signal, or content may have failed to extract cleanly."
        )
    elif word_count > 1200:
        issues.append(f"~{word_count} words - long enough that some ATS parsers truncate input.")

    return issues


def _keywords(text: str) -> Counter[str]:
    return Counter(
        word.lower()
        for word in _WORD.findall(text)
        if word.lower() not in _STOPWORDS and len(word) > 2
    )


def _keyword_match(resume_text: str, job_description: str) -> dict[str, object]:
    resume_keywords = set(_keywords(resume_text))
    posting_keywords = _keywords(job_description)
    if not posting_keywords:
        return {"match_percentage": 0.0, "matched_keywords": [], "missing_keywords": []}

    matched = sorted(word for word in posting_keywords if word in resume_keywords)
    missing = [
        word for word, _count in posting_keywords.most_common() if word not in resume_keywords
    ][:_MAX_REPORTED_MISSING_KEYWORDS]
    match_percentage = round(100 * len(matched) / len(posting_keywords), 1)
    return {
        "match_percentage": match_percentage,
        "matched_keywords": matched,
        "missing_keywords": missing,
    }


def _score(
    sections_missing: list[str],
    formatting_issues: list[str],
    keyword_match: dict[str, object] | None,
) -> int:
    score = 100
    score -= 12 * len(sections_missing)
    score -= 8 * len(formatting_issues)
    if keyword_match is not None:
        # Keyword overlap dominates the score when a target job is given -
        # it's the single strongest predictor of whether an ATS actually
        # surfaces this resume for a human to read.
        match_percentage = float(keyword_match["match_percentage"])
        score = round(score * 0.6 + match_percentage * 0.4)
    return max(0, min(100, score))


async def analyze_ats_compatibility(
    resume_text: str, job_description: str | None = None
) -> dict[str, object]:
    """Simulate an ATS's read of resume text and report compatibility issues.

    Args:
        resume_text: Resume/CV content as plain text.
        job_description: Optional target job posting text, for keyword scoring.

    Returns:
        A report dict: ``score``, ``sections_found``, ``sections_missing``,
        ``formatting_issues``, ``word_count``, and - when ``job_description``
        is given - ``keyword_match``.
    """
    logger.debug(
        "analyze_ats_compatibility: resume_len=%d has_job_description=%s",
        len(resume_text),
        job_description is not None,
    )
    sections_found, sections_missing = _find_sections(resume_text)
    formatting_issues = _find_formatting_issues(resume_text)
    keyword_match = _keyword_match(resume_text, job_description) if job_description else None
    word_count = len(_WORD.findall(resume_text))

    report: dict[str, object] = {
        "score": _score(sections_missing, formatting_issues, keyword_match),
        "sections_found": sections_found,
        "sections_missing": sections_missing,
        "formatting_issues": formatting_issues,
        "word_count": word_count,
    }
    if keyword_match is not None:
        report["keyword_match"] = keyword_match
    logger.debug("analyze_ats_compatibility: score=%d", report["score"])
    return report
