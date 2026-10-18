"""Application settings read explicitly from environment variables."""
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from config.preferences import UserPreferences


@dataclass(frozen=True)
class ApplicationSettings:
    ai_provider: str = 'groq'
    ai_model: str = 'openai/gpt-oss-20b'
    groq_api_key: str | None = field(default=None, repr=False)
    telegram_bot_token: str | None = field(default=None, repr=False)
    preferences: UserPreferences = field(default_factory=UserPreferences)
    dev_mode: bool = False
    database_path: str = 'data/matheutic.sqlite3'

    def __post_init__(self) -> None:
        if type(self.dev_mode) is not bool:
            raise ValueError('dev_mode must be a boolean')
        if (
            not isinstance(self.database_path, str) 
            or not self.database_path.strip() 
            or self.database_path == ':memory:'
            ):
            raise ValueError('MATHEUTIC_DB_PATH must name a persistent SQLite file')

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> 'ApplicationSettings':
        """Read settings from the supplied mapping or process environment."""
        env = os.environ if environ is None else environ
        dev_mode = env.get('MATHEUTIC_DEV_MODE', 'false').strip().lower()
        if dev_mode not in ('true', 'false', '1', '0', 'yes', 'no', 'on', 'off'):
            raise ValueError('MATHEUTIC_DEV_MODE must be true or false')
        return cls(
            ai_provider=env.get('AI_PROVIDER', 'groq'),
            ai_model=env.get('AI_MODEL', 'openai/gpt-oss-20b'),
            groq_api_key=env.get('GROQ_API_KEY') or None,
            telegram_bot_token=env.get('TELEGRAM_BOT_TOKEN') or None,
            dev_mode=dev_mode in ('true', '1', 'yes', 'on'),
            database_path=env.get('MATHEUTIC_DB_PATH', 'data/matheutic.sqlite3'),
            preferences=UserPreferences(
                interface_language=env.get('INTERFACE_LANGUAGE', 'en'),
                content_language=env.get('CONTENT_LANGUAGE', 'en'),
                ),
                )
