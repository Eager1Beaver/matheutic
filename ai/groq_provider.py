import json
import os

import groq
from groq import AsyncGroq
from pydantic import ValidationError

from .provider import AIProvider, AIProviderError
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
            raise AIProviderError(
                "Groq rate limit reached."
                ) from exc

        except groq.APIConnectionError as exc:
            raise AIProviderError(
                "Could not connect to Groq."
                ) from exc

        except groq.APIStatusError as exc:
            raise AIProviderError(
                f"Groq API returned status {exc.status_code}."
                ) from exc

        content = completion.choices[0].message.content

        if not content:
            raise AIProviderError(
                "Groq returned an empty response."
                )

        try:
            data = json.loads(content)
            return MathProblem.model_validate(data)

        except (json.JSONDecodeError, ValidationError) as exc:
            raise AIProviderError(
                "Groq returned an invalid MathProblem."
                ) from exc
