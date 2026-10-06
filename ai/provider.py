from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schemas import MathProblem


class AIProviderError(RuntimeError):
    """Raised when an AI provider cannot fulfill a request."""


class AIProvider(ABC):
    @abstractmethod
    async def generate_problem(
        self,
        request: str,
        language: str = "en",
        ) -> MathProblem:
        """Generate a structured arithmetic problem."""
        raise NotImplementedError
