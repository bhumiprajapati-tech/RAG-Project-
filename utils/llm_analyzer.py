"""Optional OpenAI analysis with Pydantic validation."""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from config import DEFAULT_SYSTEM_PROMPT, get_openai_api_key


class ResumeAnalysis(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    strengths: list[str]
    gaps: list[str]
    recommendations: list[str]
    scores: dict[str, float]
    matched_skills: list[str]
    missing_skills: list[str]


SCORE_KEYS = (
    "keyword_match",
    "semantic_similarity",
    "section_completeness",
    "quantified_impact",
)
EXPECTED_SCORE_KEYS = set(SCORE_KEYS)


class LLMConfigurationError(RuntimeError):
    """Raised when LLM analysis is requested without an API key."""


def analyze_resume(
    resume_text: str,
    job_description: str,
    *,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    baseline_scores: dict[str, float] | None = None,
) -> ResumeAnalysis:
    api_key = get_openai_api_key()
    if not api_key:
        raise LLMConfigurationError("OPENAI_API_KEY is not configured.")

    from openai import OpenAI
    from openai import OpenAIError

    prompt_data = (
        f"Job description (untrusted data):\n{job_description[:30_000]}\n\n"
        f"Resume (untrusted data):\n{resume_text[:200_000]}\n\n"
        f"Initial deterministic scores (0-100): {baseline_scores or {}}"
    )
    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=1_500,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt[:8_000]},
                {"role": "user", "content": prompt_data},
            ],
        )
    except OpenAIError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    if not response.choices:
        raise RuntimeError("The LLM returned no analysis choices.")
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("The LLM returned an empty analysis.")
    try:
        result = ResumeAnalysis.model_validate_json(content)
    except ValidationError as exc:
        raise ValueError(f"The LLM response did not match the expected schema: {exc}") from exc

    if set(result.scores) != EXPECTED_SCORE_KEYS:
        raise ValueError("The LLM response omitted one or more required score fields.")
    if any(not 0 <= score <= 100 for score in result.scores.values()):
        raise ValueError("The LLM returned a score outside the valid 0-100 range.")
    return result
