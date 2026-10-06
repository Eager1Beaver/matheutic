"""Typed failures for arithmetic problem generation."""
from collections.abc import Sequence

from core.problem_validator import ValidationIssue


class AIProviderError(RuntimeError):
    """Base exception for failures reported by a problem provider or generator."""


class UnsupportedProblemRequest(AIProviderError):
    """A request is outside the supported problem-generation capabilities."""

    def __init__(self, message: str = "The problem request is unsupported.", *,
                 reason: str = "unsupported_request") -> None:
        self.reason = reason
        super().__init__(message)


class GeneratedProblemInvalid(AIProviderError):
    """A generated candidate fails structural or mathematical validation."""

    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        if not self.issues:
            raise ValueError("Invalid generations must have at least one validation issue")
        super().__init__("; ".join(issue.message for issue in self.issues))


class ProblemConstraintViolation(GeneratedProblemInvalid):
    """A mathematically consistent candidate violates application constraints."""


class AIServiceUnavailable(AIProviderError):
    """The AI service cannot complete a generation call."""

    def __init__(self, *, reason: str = "service_unavailable",
                 status_code: int | None = None) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__(f"AI service unavailable: {reason}.")


class GenerationExhausted(AIProviderError):
    """All permitted generation attempts produced invalid candidates."""

    def __init__(self, failures: Sequence[GeneratedProblemInvalid]) -> None:
        self.failures = tuple(failures)
        if not self.failures:
            raise ValueError("Generation exhaustion requires at least one failed attempt")
        self.attempts = len(self.failures)
        self.last_failure = self.failures[-1]
        super().__init__(f"No valid problem after {self.attempts} generation attempts.")
