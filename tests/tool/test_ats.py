"""Unit tests for tool.tools.local.ats - pure text analysis, no mocking needed."""

from __future__ import annotations

from tool.tools.local.ats import DEFINITION, analyze_ats_compatibility

_WELL_FORMED_RESUME = """\
Jane Doe
jane.doe@example.com | (555) 123-4567

Summary
Backend engineer with 6 years building distributed systems in Python and Go.

Experience
- Led migration of the payments service from MongoDB to PostgreSQL, cutting p99 latency 40%.
- Designed and shipped a retrieval-augmented agent platform used by 50+ internal teams.
- Mentored three junior engineers through their first on-call rotations.

Education
B.S. Computer Science, State University, 2017

Skills
Python, Go, PostgreSQL, Redis, Docker, Kubernetes, FastAPI, LangGraph
"""

_POORLY_FORMED_RESUME = (
    "Jane worked at a company doing various software engineering tasks over several years "
    "and also did some other things in a different role before that including some amount "
    "of both frontend and backend work across a large number of different projects and teams "
    "and generally contributed to the success of the organization in numerous small ways over "
    "an extended period of time without much in the way of specific detail provided here at all."
)

_JOB_DESCRIPTION = """\
We're hiring a backend engineer with strong Python and PostgreSQL experience.
Familiarity with Kubernetes, Docker, and distributed systems design is a plus.
You'll build and maintain our retrieval-augmented agent platform.
"""


def test_definition_declares_required_and_optional_parameters() -> None:
    assert DEFINITION.name == "analyze_ats_compatibility"
    assert DEFINITION.parameters["required"] == ["resume_text"]
    assert "job_description" in DEFINITION.parameters["properties"]


async def test_well_formed_resume_scores_high_with_no_missing_sections() -> None:
    report = await analyze_ats_compatibility(_WELL_FORMED_RESUME)

    assert report["sections_missing"] == []
    assert set(report["sections_found"]) >= {"Summary", "Experience", "Education", "Skills"}
    assert not any("email" in issue.lower() for issue in report["formatting_issues"])
    assert not any("phone" in issue.lower() for issue in report["formatting_issues"])
    assert report["score"] >= 80


async def test_poorly_formed_resume_flags_missing_sections_and_contact_info() -> None:
    report = await analyze_ats_compatibility(_POORLY_FORMED_RESUME)

    assert "Experience" in report["sections_missing"]
    assert "Skills" in report["sections_missing"]
    assert any("email" in issue.lower() for issue in report["formatting_issues"])
    assert any("phone" in issue.lower() for issue in report["formatting_issues"])
    assert any("bullet" in issue.lower() for issue in report["formatting_issues"])
    assert report["score"] < 60


async def test_score_stays_within_bounds_for_empty_input() -> None:
    report = await analyze_ats_compatibility("")

    assert 0 <= report["score"] <= 100
    assert report["word_count"] == 0


async def test_no_keyword_match_key_without_a_job_description() -> None:
    report = await analyze_ats_compatibility(_WELL_FORMED_RESUME)

    assert "keyword_match" not in report


async def test_keyword_match_reports_overlap_and_missing_terms() -> None:
    report = await analyze_ats_compatibility(_WELL_FORMED_RESUME, job_description=_JOB_DESCRIPTION)

    keyword_match = report["keyword_match"]
    assert keyword_match["match_percentage"] > 50
    assert "python" in keyword_match["matched_keywords"]
    assert "postgresql" in keyword_match["matched_keywords"]


async def test_keyword_match_flags_missing_terms_for_an_unrelated_resume() -> None:
    report = await analyze_ats_compatibility(
        _POORLY_FORMED_RESUME, job_description=_JOB_DESCRIPTION
    )

    keyword_match = report["keyword_match"]
    assert keyword_match["match_percentage"] < 30
    assert "python" in keyword_match["missing_keywords"]
