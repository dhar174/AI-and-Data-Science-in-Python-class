"""Focused regression checks for the revised Module 3 sequence and retained adaptation resources."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


PUBLIC_ROOT = Path(__file__).resolve().parents[1]


class CurriculumAdaptationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.class_plan = (PUBLIC_ROOT / "class-plan.html").read_text(encoding="utf-8")
        cls.catalog = json.loads((PUBLIC_ROOT / "data" / "course-catalog.json").read_text(encoding="utf-8"))
        cls.catalog_paths = {record.get("catalog_path") for record in cls.catalog.get("records", [])}

    def test_module_3_titles_and_applied_sequence_are_public(self) -> None:
        required_phrases = (
            "Transformers, LLMs, SLMs, and Hugging Face",
            "Responses Python APIs and a llama.cpp-compatible local server",
            "Quantization, PEFT, LoRA, QLoRA, and adaptation choices",
            "LangChain components and LangGraph fundamentals",
            "Codex, Claude Code, and full local deployment",
            "Capstone studio I: build with coding tools",
            "Capstone studio II: evaluate, defend, and ship",
            "Pydantic", "quantization-aware", "DPO", "RLHF", "GRPO",
            "RAG", "checkpoint", "Instructor-provided",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertTrue(phrase in self.class_plan, f"Missing curriculum phrase: {phrase}")

    def test_active_adaptation_assets_are_present_in_public_catalog(self) -> None:
        required_paths = {
            "03 - Module 3 - Generative AI/04 - LLaMA and Open Models/02 - Notebooks and Code/bits_and_bytes_quantization_tour.ipynb",
            "03 - Module 3 - Generative AI/04 - LLaMA and Open Models/02 - Notebooks and Code/hf_peft_finetune_walkthrough.ipynb",
            "03 - Module 3 - Generative AI/04 - LLaMA and Open Models/02 - Notebooks and Code/tiny_llm_sft_dpo_demo.ipynb",
            "03 - Module 3 - Generative AI/04 - LLaMA and Open Models/08 - Project Packages/dependency-009/quant_load_eval_metrics.ipynb",
            "03 - Module 3 - Generative AI/04 - LLaMA and Open Models/07 - Data and Supporting Assets/fine_tuning_3b_plan.md",
        }
        missing_paths = sorted(required_paths - self.catalog_paths)
        self.assertTrue(required_paths <= self.catalog_paths, f"Missing catalog paths: {missing_paths}")


if __name__ == "__main__":
    unittest.main()
