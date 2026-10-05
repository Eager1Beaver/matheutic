"""Compatibility entry point for the existing worksheet API.

Use engine.generation for arithmetic records without PDF dependencies.
"""
from __future__ import annotations

from engine.generation import GenerationError  # retained public import


def generate_workbook(cfg: dict) -> tuple[list[list[str]], list[list[str]] | None]:
    from export.worksheet import generate_workbook as generate_printable_workbook

    return generate_printable_workbook(cfg)
