"""Administrator analytics, audit log, and system configuration."""

from __future__ import annotations

import json

import streamlit as st

from config import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_WEIGHTS,
    MAX_ANALYSIS_ROWS,
    MAX_AUDIT_ROWS,
)
from utils.llm_analyzer import EXPECTED_SCORE_KEYS, SCORE_KEYS
from utils.storage import (
    get_admin_analytics,
    get_audit_events,
    get_setting,
    record_audit_event,
    set_setting,
)


def _configured_weights() -> dict[str, float]:
    raw = get_setting("weights")
    if raw:
        try:
            values = json.loads(raw)
            if (
                isinstance(values, dict)
                and set(values) == EXPECTED_SCORE_KEYS
                and all(isinstance(value, (int, float)) and value >= 0 for value in values.values())
                and abs(sum(values.values()) - 1.0) < 0.001
            ):
                return {key: float(value) for key, value in values.items()}
        except json.JSONDecodeError:
            raise ValueError("Stored scoring weights are not valid JSON.")
        raise ValueError("Stored scoring weights are invalid.")
    return DEFAULT_WEIGHTS.copy()


def render_admin_dashboard(username: str) -> None:
    st.title("Administrator dashboard")
    analytics = get_admin_analytics()
    metric_columns = st.columns(3)
    metric_columns[0].metric("Total analyses", analytics["total_analyses"])
    metric_columns[1].metric(
        "Average match estimate", f"{analytics['average_score']:.1f}/100"
    )
    metric_columns[2].metric("Candidates analyzed", analytics["active_candidates"])

    with st.expander("Recent analysis activity", expanded=True):
        if analytics["latest"]:
            st.dataframe(
                [
                    {
                        "Candidate": row["username"],
                        "Score": row["score"],
                        "Analyzed at (UTC)": row["created_at"],
                    }
                    for row in analytics["latest"][:MAX_ANALYSIS_ROWS]
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No analysis activity yet.")

    st.subheader("Scoring weights")
    st.caption("Weights must be non-negative and sum to exactly 1.0.")
    current_weights = _configured_weights()
    with st.form("weights_form"):
        columns = st.columns(4)
        proposed = {
            key: columns[index].number_input(
                key.replace("_", " ").title(),
                min_value=0.0,
                max_value=1.0,
                value=current_weights[key],
                step=0.05,
                format="%.2f",
            )
            for index, key in enumerate(SCORE_KEYS)
        }
        save_weights = st.form_submit_button("Save weights")
    if save_weights:
        total = sum(proposed.values())
        if abs(total - 1.0) > 0.001:
            st.error(f"Weights currently total {total:.2f}; they must total 1.00.")
        else:
            set_setting("weights", json.dumps(proposed))
            record_audit_event(
                "weights_updated",
                username=username,
                details={"weights": proposed},
            )
            st.success("Scoring weights saved.")
            st.rerun()

    st.subheader("AI coaching prompt")
    st.caption(
        "This prompt is sent to the configured LLM with each AI-enabled analysis. "
        "Do not include secrets or personal data in the prompt."
    )
    prompt = get_setting("system_prompt") or DEFAULT_SYSTEM_PROMPT
    with st.form("prompt_form"):
        proposed_prompt = st.text_area(
            "System prompt",
            value=prompt,
            height=220,
            max_chars=8_000,
        )
        save_prompt = st.form_submit_button("Save prompt")
    if save_prompt:
        if not proposed_prompt.strip():
            st.error("The prompt cannot be empty.")
        else:
            set_setting("system_prompt", proposed_prompt.strip())
            record_audit_event("system_prompt_updated", username=username)
            st.success("System prompt saved.")
            st.rerun()

    st.subheader("Audit log")
    events = get_audit_events(MAX_AUDIT_ROWS)
    if events:
        st.dataframe(
            [
                {
                    "Timestamp (UTC)": event["created_at"],
                    "Username": event["username"],
                    "Event": event["event"],
                    "Details": json.dumps(event["details"], ensure_ascii=True),
                }
                for event in events
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No audit events yet.")
