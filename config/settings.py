"""Explicit environment boundary; no credentials are required for worksheets.

This reserves configuration for future adapters. It performs no network calls
and does not implicitly load .env files or read the environment at import time.
"""
from dataclasses import dataclass, field
import os
from collections.abc import Mapping

from config.preferences import UserPreferences


@dataclass(frozen=True)
class ApplicationSettings:
    ai_provider: str = 'groq'
    ai_model: str = 'openai/gpt-oss-20b'
    groq_api_key: str | None = field(default=None, repr=False)
    telegram_bot_token: str | None = field(default=None, repr=False)
    preferences: UserPreferences = field(default_factory=UserPreferences)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> 'ApplicationSettings':
        env = os.environ if environ is None else environ
        return cls(
            ai_provider=env.get('AI_PROVIDER', 'groq'),
            ai_model=env.get('AI_MODEL', 'openai/gpt-oss-20b'),
            groq_api_key=env.get('GROQ_API_KEY') or None,
            telegram_bot_token=env.get('TELEGRAM_BOT_TOKEN') or None,
            preferences=UserPreferences(
                interface_language=env.get('INTERFACE_LANGUAGE', 'en'),
                content_language=env.get('CONTENT_LANGUAGE', 'en'),
            ),
        )
