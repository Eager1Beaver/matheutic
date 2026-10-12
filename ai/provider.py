from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .errors import AIProviderError

if TYPE_CHECKING:
    from .schemas import (
        CoachInterpretation,
        HintWording,
        MathProblem,
        ProblemContent,
        RequestInterpretation,
        StoryReview,
    )


class AIProvider(ABC):
    async def review_story(
            self, 
            request: str, 
            language: str = "en", 
            *, dev_mode: bool = False,
            ) -> StoryReview:
        """Independently read a story and reconstruct its arithmetic question."""
        from core.problem_validator import ValidationIssue

        from .errors import GeneratedProblemInvalid

        raise GeneratedProblemInvalid([
            ValidationIssue("story_review_unavailable", "The provider cannot review story problems.")
            ])

    async def interpret_turn(
            self, 
            request: str, 
            language: str = "en", 
            *, 
            dev_mode: bool = False,
            ) -> CoachInterpretation:
        """Interpret a learner message against a supplied coach context."""
        from core.problem_validator import ValidationIssue

        from .errors import RequestInterpretationInvalid

        raise RequestInterpretationInvalid([
            ValidationIssue("coach_interpretation_unavailable", "The provider cannot interpret coach turns.")
            ])

    async def phrase_hint(
            self, 
            request: str, 
            language: str = "en", 
            *, 
            dev_mode: bool = False,
            ) -> HintWording:
        """Phrase verbal guidance from application-selected tutoring facts."""
        from core.problem_validator import ValidationIssue

        from .errors import HintGenerationInvalid

        raise HintGenerationInvalid([
            ValidationIssue("hint_wording_unavailable", "The provider cannot phrase hints.")
            ])

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
