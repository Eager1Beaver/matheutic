import json
import os
from typing import TypeVar

import groq
from groq import AsyncGroq
from pydantic import BaseModel, ValidationError

from core.problem_validator import ValidationIssue

from .errors import (
    AIServiceUnavailable,
    GeneratedProblemInvalid,
    RequestInterpretationInvalid,
    )
from .prompts import GENERATE_PROBLEM_PROMPT, INTERPRET_REQUEST_PROMPT
from .provider import AIProvider
from .schemas import MathProblem, RequestInterpretation

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class GroqProvider(AIProvider):
    def __init__(self) -> None:
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. "
                "Add it to your .env file."
                )

        self.model = os.getenv(
            "AI_MODEL",
            "openai/gpt-oss-20b",
            )

        self.client = AsyncGroq(
            api_key=api_key,
            timeout=20.0,
            max_retries=0,
            )

    async def generate_problem(
            self,
            request: str,
            language: str = "en",
            ) -> MathProblem:
        """Return a schema-validated arithmetic candidate from Groq."""
        return await self._structured_completion(
            request, language, system_prompt=GENERATE_PROBLEM_PROMPT,
            schema_name="math_problem", output_model=MathProblem,
            invalid_error=GeneratedProblemInvalid,
            )

    async def interpret_request(self, request: str, language: str = "en") -> RequestInterpretation:
        """Return a schema-validated intent and arithmetic requirements from Groq."""
        return await self._structured_completion(
            request, language, system_prompt=INTERPRET_REQUEST_PROMPT,
            schema_name="request_interpretation", output_model=RequestInterpretation,
            invalid_error=RequestInterpretationInvalid,
        )

    async def _structured_completion(
        self, request: str, language: str, *, system_prompt: str,
        schema_name: str, output_model: type[OutputModel],
        invalid_error: type[GeneratedProblemInvalid] | type[RequestInterpretationInvalid],
        ) -> OutputModel:
        """Request typed JSON and map service and structured-output failures."""
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Target language: {language}\n\n"
                            f"User input:\n{request}"
                            ),
                    },
                    ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": output_model.model_json_schema(),
                        },
                        },
                        )

        except groq.RateLimitError as exc:
            raise AIServiceUnavailable(reason="rate_limit", status_code=429) from exc

        except groq.APITimeoutError as exc:
            raise AIServiceUnavailable(reason="timeout") from exc

        except groq.APIConnectionError as exc:
            raise AIServiceUnavailable(reason="connection") from exc

        except groq.APIStatusError as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            error = body.get("error", body)
            code = error.get("code") if isinstance(error, dict) else None
            if exc.status_code == 400 and isinstance(code, str) and code in {
                "json_validate_failed", "json_schema_validation_failed", "schema_validation_failed",
                }:
                raise invalid_error([
                    ValidationIssue("structured_output_rejected", "The service rejected its generated JSON.")
                    ]) from exc
            raise AIServiceUnavailable(reason="http_status", status_code=exc.status_code) from exc

        except groq.APIError as exc:
            raise AIServiceUnavailable(reason="invalid_service_response") from exc

        content = completion.choices[0].message.content if completion.choices else None

        if not content:
            raise invalid_error([
                ValidationIssue("empty_response", "The service returned no structured content.")
                ])

        try:
            data = json.loads(content)
        except (ValueError, RecursionError) as exc:
            raise invalid_error([
                ValidationIssue("invalid_json", "Generated content is not valid JSON.")
                ]) from exc

        try:
            return output_model.model_validate(data)
        except ValidationError as exc:
            # Error types are useful diagnostics; Pydantic input values can contain private text.
            error_types = sorted({error["type"] for error in exc.errors(include_input=False)})
            raise invalid_error([
                ValidationIssue("invalid_schema", "Structured output validation failed: " + ", ".join(error_types))
                ]) from exc
