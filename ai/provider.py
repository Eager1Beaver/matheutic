from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .errors import AIProviderError

if TYPE_CHECKING:
    from .schemas import MathProblem, ProblemContent, RequestInterpretation


class AIProvider(ABC):
    @abstractmethod
    async def interpret_request(
        self, 
        request: str, 
        language: str = "en", 
        *, 
        dev_mode: bool = False,
        ) -> RequestInterpretation:
        """Classify a message and extract a structured arithmetic request."""
        raise NotImplementedError

    @abstractmethod
    async def generate_problem(
        self,
        request: str,
        language: str = "en",
        *,
        dev_mode: bool = False,
        ) -> ProblemContent | MathProblem:
        """Generate a structured candidate, or raise a typed AIProviderError."""
        raise NotImplementedError
