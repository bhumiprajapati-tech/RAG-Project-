"""Candidate resume analysis and score history."""

from __future__ import annotations

import json
import re

import streamlit as st

from config import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_WEIGHTS,
    MAX_JOB_DESCRIPTION_CHARS,
    MAX_UPLOAD_BYTES,
)
from utils.llm_analyzer import (
    EXPECTED_SCORE_KEYS,
    LLMConfigurationError,
    ResumeAnalysis,
    SCORE_KEYS,
    analyze_resume,
)
from utils.pdf_parser import PDFParseError, extract_text
from utils.storage import get_setting, get_user_analyses, record_audit_event, save_analysis
from utils.vector_engine import KeywordMatch, match_keywords

_SECTION_ALIASES = {
    "experience": ("experience", "employment", "work history"),
    "education": ("education", "academic"),
    "skills": ("skills", "technical skills", "core competencies"),
    "summary": ("summary", "profile", "objective"),
    "projects": ("projects", "selected projects"),
}


def _score_local(
    resume_text: str, job_description: str
) -> tuple[dict[str, float], KeywordMatch]:
    matching = match_keywords(resume_text, job_description)
    resume_lower = resume_text.lower()
    sections_found = sum(
        any(alias in resume_lower for alias in aliases)
        for aliases in _SECTION_ALIASES.values()
    )
    section_score = sections_found / len(_SECTION_ALIASES) * 100
    quantified_count = len(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", resume_text))
    impact_score = min(100.0, quantified_count / 5 * 100)
    scores = {
        "keyword_match": float(matching["keyword_match"]),
        "semantic_similarity": float(matching["semantic_similarity"]),
        "section_completeness": round(section_score, 1),
        "quantified_impact": round(impact_score, 1),
    }
    return scores, matching


def _weights() -> dict[str, float]:
    configured = get_setting("weights")
    if not configured:
        return DEFAULT_WEIGHTS.copy()
    try:
        value = json.loads(configured)
    except json.JSONDecodeError:
        raise ValueError("Stored scoring weights are not valid JSON.")
    if (
        isinstance(value, dict)
        and set(value) == EXPECTED_SCORE_KEYS
        and all(isinstance(score, (int, float)) and score >= 0 for score in value.values())
        and abs(sum(value.values()) - 1.0) < 0.001
    ):
        return {key: float(score) for key, score in value.items()}
    raise ValueError("Stored scoring weights are invalid; ask an administrator to review them.")


def _weighted_score(scores: dict[str, float], weights: dict[str, float]) -> float:
    return round(sum(scores[key] * weights[key] for key in weights), 1)


def _local_report(scores: dict[str, float], matching: KeywordMatch) -> ResumeAnalysis:
    matched = matching["matched_keywords"]
    missing = matching["missing_keywords"]
    return ResumeAnalysis(
        summary=(
            "This report uses local keyword and document-structure checks only. "
            "It is not an AI-generated assessment."
        ),
        strengths=[f"Matched job-description terms: {', '.join(matched[:10]) or 'none detected'}."],
        gaps=[f"Terms not found in the resume: {', '.join(missing[:10]) or 'none detected'}."],
        recommendations=[
            "Tailor the resume using only skills and achievements that are accurate.",
            "Add measurable outcomes where you can substantiate them.",
            "Use clear section headings and concise, role-relevant language.",
        ],
        scores=scores,
        matched_skills=matched[:20],
        missing_skills=missing[:20],
    )


def _render_report(
    report: ResumeAnalysis, score: float, scores: dict[str, float]
) -> None:
    st.subheader(f"ATS match estimate: {score:.1f}/100")
    st.caption(
        "A heuristic estimate, not a hiring prediction. Local matching is lexical "
        "TF-IDF; results may differ across applicant tracking systems."
    )
    st.progress(min(max(score / 100, 0.0), 1.0))
    labels = {
        "keyword_match": "Keyword match",
        "semantic_similarity": "Text similarity",
        "section_completeness": "Section completeness",
        "quantified_impact": "Quantified impact",
    }
    columns = st.columns(4)
    for column, key in zip(columns, SCORE_KEYS):
        column.metric(labels[key], f"{scores[key]:.0f}/100")
    st.write(report.summary)

    left, right = st.columns(2)
    with left:
        st.markdown("#### Strengths")
        for item in report.strengths:
            st.markdown(f"- {item}")
        st.markdown("#### Suggested improvements")
        for item in report.recommendations:
            st.markdown(f"- {item}")
    with right:
        st.markdown("#### Gaps to review")
        for item in report.gaps:
            st.markdown(f"- {item}")
        st.markdown("#### Matched / missing skills")
        st.write("Matched:", ", ".join(report.matched_skills) or "None detected")
        st.write("Missing:", ", ".join(report.missing_skills) or "None detected")


def render_user_dashboard(username: str) -> None:
    st.title("Resume analysis")
    st.write(
        "Upload a text-based PDF resume and paste the target job description. "
        "Your resume text is processed for this request and is not stored in the database."
    )

    uploaded = st.file_uploader(
        "Resume PDF",
        type=["pdf"],
        accept_multiple_files=False,
        help=f"PDF only, up to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
    )
    job_description = st.text_area(
        "Target job description",
        height=220,
        max_chars=MAX_JOB_DESCRIPTION_CHARS,
        placeholder="Paste the full job description here...",
    )
    use_ai = st.toggle(
        "Use AI-generated coaching (requires OPENAI_API_KEY)",
        value=False,
    )

    if st.button("Analyze resume", type="primary", disabled=uploaded is None):
        if not uploaded:
            st.warning("Upload a PDF resume to continue.")
            return
        if not job_description.strip():
            st.warning("Paste a job description to continue.")
            return

        try:
            resume_text = extract_text(uploaded.getvalue())
        except PDFParseError as exc:
            st.error(str(exc))
            return
        baseline_scores, matching = _score_local(resume_text, job_description)

        if use_ai:
            stored_prompt = get_setting("system_prompt") or DEFAULT_SYSTEM_PROMPT
            try:
                report = analyze_resume(
                    resume_text,
                    job_description,
                    system_prompt=stored_prompt,
                    baseline_scores=baseline_scores,
                )
                scores = report.scores
                st.caption("AI coaching enabled. Verify suggestions before editing your resume.")
            except LLMConfigurationError as exc:
                st.error(str(exc))
                return
            except (RuntimeError, ValueError) as exc:
                st.error(f"Could not complete AI analysis: {exc}")
                return
        else:
            report = _local_report(baseline_scores, matching)
            scores = baseline_scores
            st.info("AI coaching is off. Showing local, deterministic matching checks.")

        weights = _weights()
        final_score = _weighted_score(scores, weights)
        save_analysis(username, final_score, scores)
        record_audit_event(
            "resume_analyzed",
            username=username,
            details={"score": final_score, "ai_enabled": use_ai},
        )
        st.session_state["latest_report"] = {
            "report": report.model_dump(),
            "score": final_score,
            "scores": scores,
        }

    latest = st.session_state.get("latest_report")
    if latest:
        st.divider()
        report = ResumeAnalysis.model_validate(latest["report"])
        _render_report(report, latest["score"], latest["scores"])

    st.divider()
    st.subheader("Your recent analyses")
    history = get_user_analyses(username)
    if history:
        st.dataframe(
            [
                {"Analyzed at (UTC)": row["created_at"], "ATS estimate": row["score"]}
                for row in history
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No analyses yet.")
