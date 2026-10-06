"""Telegram handlers for presenting validated arithmetic problems and generation fallbacks."""
from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ai.errors import (
    AIProviderError,
    AIServiceUnavailable,
    GeneratedProblemInvalid,
    GenerationExhausted,
    ProblemConstraintViolation,
    UnsupportedProblemRequest,
    )
from ai.orchestrator import GenerationRejection, ProblemGenerator, ValidatedProblem
from ai.provider import AIProvider
from config.settings import ApplicationSettings
from core.constraints import ProblemConstraints
from core.expression import ExpressionAnalysis, ExpressionError, analyze_expression

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import Application, ContextTypes

logger = logging.getLogger(__name__)


def generation_fallback(error: AIProviderError) -> str:
    """Return a learner-facing explanation without provider or validation details."""
    if isinstance(error, UnsupportedProblemRequest):
        if error.reason == "unsupported_language":
            return "I can currently create problems in English. Please ask for an English problem."
        if error.reason == "impossible_constraints":
            return (
                "Those constraints don't allow a solvable arithmetic problem. "
                "Please adjust the operations or number range."
                )
        if error.reason == "empty_request":
            return "Describe the kind of arithmetic problem you'd like."
        return (
            "I can create problems using addition, subtraction, multiplication and division. "
            "Please try a different request or simpler constraints."
            )
    if isinstance(error, AIServiceUnavailable):
        if error.reason == "rate_limit":
            return "I'm handling too many requests right now. Please try again in a little while."
        return "The problem service is unavailable right now. Please try again in a little while."
    if isinstance(error, GenerationExhausted):
        if all(isinstance(failure, ProblemConstraintViolation) for failure in error.failures):
            return (
                "I couldn't generate a valid arithmetic problem matching those constraints. "
                "Please adjust them or try again."
                )
        return "I couldn't generate a valid arithmetic problem. Please try again."
    if isinstance(error, ProblemConstraintViolation):
        return (
            "I couldn't generate a problem matching those constraints. "
            "Please adjust them or try again."
            )
    if isinstance(error, GeneratedProblemInvalid):
        return "I couldn't generate a valid arithmetic problem. Please try again."
    return "I couldn't generate a problem right now. Please try again."


def _log_failure(error: AIProviderError) -> None:
    """Log failure categories and safe diagnostics without SDK exception payloads."""
    if isinstance(error, AIServiceUnavailable):
        logger.warning("Problem generation failed: category=%s reason=%s status=%s",
                       type(error).__name__, error.reason, error.status_code)
    elif isinstance(error, UnsupportedProblemRequest):
        logger.warning("Problem generation failed: category=%s reason=%s",
                       type(error).__name__, error.reason)
    elif isinstance(error, GenerationExhausted):
        logger.warning("Problem generation failed: category=%s attempts=%s last_failure=%s",
                       type(error).__name__, error.attempts, type(error.last_failure).__name__)
    elif isinstance(error, GeneratedProblemInvalid):
        logger.warning("Problem generation failed: category=%s issues=%s", type(error).__name__,
                       "; ".join(f"{issue.code}: {issue.message}" for issue in error.issues))
    else:
        logger.warning("Problem generation failed: category=%s", type(error).__name__)


def _candidate_details(problem) -> str:
    """Format a candidate's statement and mathematical metadata for development inspection."""
    return (
        f"Expression: {problem.expression}\n"
        f"Declared answer: {problem.answer}\n"
        f"Declared operations: {', '.join(problem.operations)}\n"
        f"Difficulty: {getattr(problem, 'difficulty', 'unspecified')}\n"
        f"Language: {getattr(problem, 'language', 'unspecified')}\n"
        f"Statement: {problem.statement[:1000]}"
        )


def _solution_details(analysis: ExpressionAnalysis) -> str:
    """Format the exact computed answer and solution steps for inspection."""
    return (
        f"Computed answer: {analysis.value}\nSolution steps:\n"
        + "\n".join(
            f"{step.left} {step.operation} {step.right} = {step.result}"
            for step in analysis.steps
            )
            )


async def _send_development_data(message, rejections: list[GenerationRejection],
                                 result: ValidatedProblem | None = None) -> None:
    """Send bounded inspection messages for rejected and verified candidates."""
    for rejection in rejections:
        details = (
            f"[Development data - REJECTED, attempt {rejection.attempt}]\n"
            f"Category: {type(rejection.error).__name__}\n"
            + "\n".join(
                f"{issue.code}: {issue.message}" for issue in rejection.error.issues
                )
            )
        if rejection.problem is not None:
            details += "\n" + _candidate_details(rejection.problem)
            try:
                analysis = analyze_expression(rejection.problem.expression)
            except ExpressionError as error:
                details += f"\nExpression analysis rejected: {error.code}"
            else:
                details += "\n" + _solution_details(analysis)
        await message.reply_text(details[:4000], parse_mode=None)
    
    if result is not None:
        details = (
            f"[Development data - VERIFIED, attempt {result.attempts}]\n"
            + _candidate_details(result.problem)
            + "\n" + _solution_details(result.analysis)
        )
        await message.reply_text(details[:4000], parse_mode=None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome a learner and invite an arithmetic request."""
    message = update.effective_message
    if message is None:
        return
    user = update.effective_user
    first_name = user.first_name if user else "there"
    await message.reply_text(
        f"Hello, {first_name}. I'm Matheutic.\n\n"
        "Describe the kind of arithmetic problem you'd like."
        )


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Present a verified statement or a failure-specific fallback."""
    message = update.effective_message
    if message is None or not message.text:
        return
    generator = ProblemGenerator(
        context.bot_data["ai_provider"], context.bot_data.get("problem_constraints"),
        max_attempts=context.bot_data.get("max_generation_attempts", 3),
        )
    dev_mode = context.bot_data.get("dev_mode", False)
    rejections: list[GenerationRejection] | None = [] if dev_mode else None
    try:
        result = await generator.generate(
            request=message.text, language="en",
            on_rejection=rejections.append if rejections is not None else None,
            )
    except AIProviderError as error:
        _log_failure(error)
        await message.reply_text(generation_fallback(error))
        if rejections is not None:
            await _send_development_data(message, rejections)
        return
    await message.reply_text(result.problem.statement)
    if rejections is not None:
        await _send_development_data(message, rejections, result)


def create_application(token: str, provider: AIProvider,
                       constraints: ProblemConstraints | None = None, *,
                       dev_mode: bool = False, max_generation_attempts: int = 3) -> Application:
    """Build a polling application with a validation policy and optional development output."""
    generator = ProblemGenerator(provider, constraints, max_attempts=max_generation_attempts)
    if type(dev_mode) is not bool:
        raise ValueError("dev_mode must be a boolean")
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    application = Application.builder().token(token).build()
    application.bot_data.update({
        "ai_provider": provider,
        "problem_constraints": generator.constraints,
        "max_generation_attempts": generator.max_attempts,
        "dev_mode": dev_mode,
        })
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    return application


def main() -> None:
    """Load settings and run Telegram long polling with optional development diagnostics."""
    parser = argparse.ArgumentParser(description="Run the Matheutic Telegram coach.")
    parser.add_argument("--dev", action=argparse.BooleanOptionalAction, default=None,
                        help="Display mathematical development data in Telegram (default: off).")
    args = parser.parse_args()

    from dotenv import load_dotenv

    from ai.groq_provider import GroqProvider

    load_dotenv()

    try:
        settings = ApplicationSettings.from_env()
    except ValueError as error:
        parser.error(str(error))
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to your .env file.")
    if settings.ai_provider != "groq":
        raise RuntimeError("AI_PROVIDER must be groq.")
    dev_mode = settings.dev_mode if args.dev is None else args.dev
    logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    application = create_application(settings.telegram_bot_token, GroqProvider(), dev_mode=dev_mode)
    logger.info("Bot is running. Development mode: %s. Press Ctrl+C to stop.", dev_mode)
    application.run_polling()


if __name__ == "__main__":
    main()
