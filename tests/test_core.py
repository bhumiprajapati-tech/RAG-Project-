from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import auth
import utils.storage as storage
from utils.llm_analyzer import ResumeAnalysis
from utils.pdf_parser import PDFParseError, extract_text
from utils.vector_engine import cosine_similarity_score, match_keywords


class AuthenticationTests(unittest.TestCase):
    def test_password_hash_and_candidate_role(self) -> None:
        password_hash = auth.hash_password("a-long-test-password")
        users = {
            "candidate": {
                "password_hash": password_hash,
                "role": "candidate",
            }
        }
        with patch.dict(os.environ, {"ATS_USERS_JSON": json.dumps(users)}):
            self.assertEqual(
                auth.authenticate("candidate", "a-long-test-password"),
                {"username": "candidate", "role": "candidate"},
            )
            self.assertIsNone(auth.authenticate("candidate", "incorrect"))
            self.assertIsNone(auth.authenticate("unknown", "incorrect"))

    def test_role_check_rejects_untrusted_role(self) -> None:
        self.assertFalse(auth.require_role({"username": "x", "role": "root"}, {"admin"}))


class MatchingTests(unittest.TestCase):
    def test_matching_returns_bounded_scores_and_terms(self) -> None:
        result = match_keywords(
            "Python engineer with AWS and SQL experience",
            "Seeking a Python engineer with AWS, SQL, and Docker skills",
        )
        self.assertGreater(result["keyword_match"], 0)
        self.assertGreaterEqual(result["semantic_similarity"], 0)
        self.assertLessEqual(result["semantic_similarity"], 100)
        self.assertIn("python", result["matched_keywords"])
        self.assertIn("docker", result["missing_keywords"])

    def test_empty_text_has_zero_similarity(self) -> None:
        self.assertEqual(cosine_similarity_score("", ""), 0.0)


class PersistenceTests(unittest.TestCase):
    def test_settings_and_private_analysis_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original_path = storage.DATABASE_PATH
            storage.DATABASE_PATH = str(Path(directory) / "app.sqlite3")
            try:
                storage.init_db()
                storage.set_setting("example", "value")
                storage.save_analysis("candidate-a", 75.0, {"keyword_match": 75.0})
                storage.save_analysis("candidate-b", 90.0, {"keyword_match": 90.0})
                self.assertEqual(storage.get_setting("example"), "value")
                self.assertEqual(len(storage.get_user_analyses("candidate-a")), 1)
                self.assertEqual(storage.get_user_analyses("candidate-a")[0]["score"], 75.0)
            finally:
                storage.DATABASE_PATH = original_path


class PDFTests(unittest.TestCase):
    def test_rejects_non_pdf_upload(self) -> None:
        with self.assertRaises(PDFParseError):
            extract_text(b"not a PDF")


class StructuredOutputTests(unittest.TestCase):
    def test_resume_analysis_schema(self) -> None:
        report = ResumeAnalysis.model_validate(
            {
                "summary": "A short summary",
                "strengths": [],
                "gaps": [],
                "recommendations": [],
                "scores": {
                    "keyword_match": 50,
                    "semantic_similarity": 60,
                    "section_completeness": 70,
                    "quantified_impact": 80,
                },
                "matched_skills": [],
                "missing_skills": [],
            }
        )
        self.assertEqual(report.scores["keyword_match"], 50)


if __name__ == "__main__":
    unittest.main()
