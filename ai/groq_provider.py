import json
import os

import groq
from groq import AsyncGroq
from pydantic import ValidationError

from core.problem_validator import ValidationIssue

from .errors import AIServiceUnavailable, GeneratedProblemInvalid
from .provider import AIProvider
from .schemas import MathProblem

# TODO: expect to have a prompts subfolder with prompt templates for different use cases
# e.g. problem generation and hints
SYSTEM_PROMPT = """
You generate arithmetic word problems for Matheutic.

Matheutic is an arithmetic practice application for children
developing arithmetic skills and adults doing regular mental practice.

Generate exactly one arithmetic word problem satisfying the user's request.

Rules:
- The mathematical problem must be solvable.
- The expression must represent exactly the story in the statement.
- The answer must be the result of that expression.
- Use only arithmetic operations: +, -, *, /.
- Use non-negative decimal integer literals without unary signs.
- List each distinct used operator exactly once in operations.
- The final answer must be an integer.
- Every division must produce an exact integer result, including intermediate steps.
- Avoid ambiguous wording.
- Keep the problem concise.
- Difficulty must be an integer from 1 to 5.
- All learner-visible text must use the requested language.
- Do not include hints, explanations, commentary, or markdown.
""".strip()


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
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT, 
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Target language: {language}\n\n"
                            f"Problem request:\n{request}"
                            ),
                    },
                    ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "math_problem",
                        "strict": True,
                        "schema": MathProblem.model_json_schema(),
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
                raise GeneratedProblemInvalid([
                    ValidationIssue("structured_output_rejected", "The service rejected its generated JSON.")
                    ]) from exc
            raise AIServiceUnavailable(reason="http_status", status_code=exc.status_code) from exc

        except groq.APIError as exc:
            raise AIServiceUnavailable(reason="invalid_service_response") from exc

        content = completion.choices[0].message.content if completion.choices else None

        if not content:
            raise GeneratedProblemInvalid([
                ValidationIssue("empty_response", "The service returned no problem content.")
                ])

        try:
            data = json.loads(content)
        except (ValueError, RecursionError) as exc:
            raise GeneratedProblemInvalid([
                ValidationIssue("invalid_json", "Generated content is not valid problem JSON.")
                ]) from exc

        try:
            return MathProblem.model_validate(data)
        except ValidationError as exc:
            # Error types are useful diagnostics; Pydantic input values can contain private text.
            error_types = sorted({error["type"] for error in exc.errors(include_input=False)})
            raise GeneratedProblemInvalid([
                ValidationIssue("invalid_schema", "Problem schema validation failed: " + ", ".join(error_types))
                ]) from exc
