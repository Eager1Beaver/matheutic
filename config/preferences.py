"""Validated interface and content language preferences."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UserPreferences:
    interface_language: str = 'en'
    content_language: str = 'en'

    def __post_init__(self):
        for value in (self.interface_language, self.content_language):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', value):
                raise ValueError('language must be a language tag such as en or pt-BR')
