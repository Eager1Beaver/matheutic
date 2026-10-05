import os

import groq
from groq import AsyncGroq

from .provider import AIProvider

# TODO: expect to have a prompts subfolder with prompt templates for different use cases
# e.g. problem generation and hints
SYSTEM_PROMPT = """
You are Matheutic, an assistant for arithmetic practice.

Matheutic is intended for children developing arithmetic skills
and adults using arithmetic for regular mental practice.

For now:
- always reply in English;
- be concise and clear;
- avoid unnecessary verbosity;
- be friendly without being childish;
- focus primarily on arithmetic and mathematical practice.

This is currently a development version of Matheutic.
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

    async def reply(self, message: str) -> str:
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
                        "content": message,
                    },
                ],
            )

        except groq.RateLimitError as exc:
            raise RuntimeError(
                "Groq rate limit reached."
            ) from exc

        except groq.APIConnectionError as exc:
            raise RuntimeError(
                "Could not connect to Groq."
            ) from exc

        except groq.APIStatusError as exc:
            raise RuntimeError(
                f"Groq API returned status {exc.status_code}."
            ) from exc

        content = completion.choices[0].message.content

        if not content:
            raise RuntimeError(
                "Groq returned an empty response."
            )

        return content.strip()