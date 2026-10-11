import json
import logging
import os
from functools import lru_cache
from typing import TypeVar

import groq
from groq import AsyncGroq
from pydantic import BaseModel, ValidationError

from core.problem_validator import ValidationIssue

from .errors import (
	AIServiceUnavailable,
	GeneratedProblemInvalid,
	HintGenerationInvalid,
	RequestInterpretationInvalid,
)
from .prompts import (
	GENERATE_PROBLEM_DEV_PROMPT,
	GENERATE_PROBLEM_PROMPT,
	INTERPRET_COACH_TURN_PROMPT,
	INTERPRET_REQUEST_PROMPT,
	PHRASE_HINT_PROMPT,
)
from .provider import AIProvider
from .schemas import (
	CoachInterpretation,
	HintWording,
	MathProblem,
	ProblemContent,
	RequestInterpretation,
)

REASONING_EFFORT = "low"  # GPT-OSS supports "low", "medium", or "high".

logger = logging.getLogger(__name__)
OutputModel = TypeVar("OutputModel", bound=BaseModel)


@lru_cache(maxsize=5)
def _completion_schema(output_model: type[BaseModel]) -> dict:
	"""Build a strict completion schema without automatic title annotations."""
	def trim(node):
		if isinstance(node, list):
			return [trim(item) for item in node]
		if not isinstance(node, dict):
			return node
		return {
			key: ({name: trim(value) for name, value in item.items()}
				  if key in {"properties", "$defs"} else trim(item))
			for key, item in node.items() if key != "title"
			}

	return trim(output_model.model_json_schema())


def _log_usage(completion, *, phase: str) -> None:
	"""Log available token counts without recording messages or model reasoning."""
	usage = completion.usage
	if usage is None:
		logger.info("LLM usage: phase=%s unavailable", phase)
		return
	details = getattr(usage, "completion_tokens_details", None)
	logger.info(
		"LLM usage: phase=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s reasoning_tokens=%s",
		phase, usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
		getattr(details, "reasoning_tokens", None),
		)


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
			*,
			dev_mode: bool = False,
			) -> ProblemContent | MathProblem:
		"""Return a schema-validated arithmetic candidate from Groq."""
		return await self._structured_completion(
			request, language,
			system_prompt=GENERATE_PROBLEM_DEV_PROMPT if dev_mode else GENERATE_PROBLEM_PROMPT,
			schema_name="math_problem", output_model=MathProblem if dev_mode else ProblemContent,
			invalid_error=GeneratedProblemInvalid, dev_mode=dev_mode,
			)

	async def interpret_request(
			self, 
			request: str, 
			language: str = "en", 
			*, 
			dev_mode: bool = False,
			) -> RequestInterpretation:
		"""Return a schema-validated intent and arithmetic requirements from Groq."""
		return await self._structured_completion(
			request, language, system_prompt=INTERPRET_REQUEST_PROMPT,
			schema_name="request_interpretation", output_model=RequestInterpretation,
			invalid_error=RequestInterpretationInvalid, dev_mode=dev_mode,
			)

	async def interpret_turn(
			self, 
			request: str, 
			language: str = "en", 
			*, 
			dev_mode: bool = False,
			) -> CoachInterpretation:
		"""Return a structured learner action using the supplied problem context."""
		return await self._structured_completion(
			request, language, system_prompt=INTERPRET_COACH_TURN_PROMPT,
			schema_name="coach_interpretation", output_model=CoachInterpretation,
			invalid_error=RequestInterpretationInvalid, dev_mode=dev_mode,
			)

	async def phrase_hint(
			self, 
			request: str, 
			language: str = "en", 
			*, 
			dev_mode: bool = False,
			) -> HintWording:
		"""Return a verbal introduction to verified mathematical guidance."""
		return await self._structured_completion(
			request, language, system_prompt=PHRASE_HINT_PROMPT,
			schema_name="hint_wording", output_model=HintWording,
			invalid_error=HintGenerationInvalid, dev_mode=dev_mode,
			)

	async def _structured_completion(
			self, 
			request: str, 
			language: str, 
			*, 
			system_prompt: str,
			schema_name: str, output_model: type[OutputModel],
			invalid_error: type[GeneratedProblemInvalid] | type[RequestInterpretationInvalid],
			dev_mode: bool,
			) -> OutputModel:
		"""Request typed JSON and map service and structured-output failures."""
		if type(dev_mode) is not bool:
			raise ValueError("dev_mode must be a boolean")
		try:
			completion = await self.client.chat.completions.create(
				model=self.model,
				reasoning_effort=REASONING_EFFORT,
				messages=[
					{
						"role": "system",
						"content": system_prompt,
					},
					{
						"role": "user",
						"content": (
							f"Language: {language}\n{request}"
							),
					},
					],
				response_format={
					"type": "json_schema",
					"json_schema": {
						"name": schema_name,
						"strict": True,
						"schema": _completion_schema(output_model),
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

		if dev_mode:
			_log_usage(completion, phase=schema_name)
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
