"""Telegram transport for conversational arithmetic coaching and diagnostics."""
from __future__ import annotations

import argparse
import json
import logging
from copy import deepcopy
from typing import TYPE_CHECKING

from ai.errors import (
    AIProviderError,
    AIServiceUnavailable,
    GeneratedProblemInvalid,
    GenerationExhausted,
    ProblemConstraintViolation,
    RequestInterpretationInvalid,
    UnsupportedProblemRequest,
)
from ai.intent import RequestDecision
from ai.orchestrator import GenerationRejection, ProblemGenerator, ValidatedProblem
from ai.provider import AIProvider
from coach import messages
from coach.flow import Coach
from coach.session import InMemorySessionStore
from config.settings import ApplicationSettings
from core.constraints import ProblemConstraints
from core.expression import ExpressionAnalysis, ExpressionError, analyze_expression

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import Application, ContextTypes

logger = logging.getLogger(__name__)

MAX_GEN_ATTEMPTS = 2 # 3

# TODO: put custom messages in a separate file, e.g. coach/messages, import from there
def generation_fallback(error: AIProviderError) -> str:
    """Return a learner-facing explanation without provider or validation details."""
    if isinstance(error, RequestInterpretationInvalid):
        return (
            "I couldn't understand that request reliably. Please try rephrasing it, "
            "for example: 'Give me an easy addition problem with numbers below 20.'"
            )
    if isinstance(error, UnsupportedProblemRequest):
        if error.reason == "unsupported_difficulty":
            return "Choose a difficulty from 1 to 5. To go beyond level 5, ask for a harder problem while practicing at level 5."
        if error.reason == "unsupported_custom_problem":
            return "Tell me the operations, number ranges, or difficulty you want to practice, and I'll choose a problem for you. Specifying an exact calculation or fixed numbers is not supported."
        if error.reason == "unsupported_language":
            return "I can currently create problems in English. Please ask for an English problem."
        if error.reason == "impossible_constraints":
            return (
                "Those constraints don't allow a solvable arithmetic problem. "
                "Please adjust the operations or number range."
                )
        if error.reason == "empty_request":
            return "Describe the kind of arithmetic problem you'd like."
        if error.reason == "unsupported_math":
            return (
                "I can create addition, subtraction, multiplication and exact division problems "
                "using whole numbers, including zero. Numbers and results must be zero or higher."
                )
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


def request_reply(decision: RequestDecision, *, active: bool = False) -> str:
    """Return an application-owned invitation or scope explanation for a routed message."""
    if decision.intent == "off_topic":
        if active:
            return ("Hello! " if decision.reason == "greeting" else "I'm here to help with maths practice. ") + (
                "You can continue the current problem, ask for a hint, or request another problem."
                )
        if decision.reason == "greeting":
            return "Hello! Would you like to practice addition, subtraction, multiplication or division?"
        return (
            "I'm here to help with maths practice. Would you like an addition, "
            "subtraction, multiplication or division problem?"
            )
    if decision.intent == "unsupported_request":
        if decision.reason == "unsupported_task":
            return (
                "I can create one arithmetic word problem at a time. "
                "Please ask for a single addition, subtraction, multiplication or division problem,"
                "or their combination."
                )
        if decision.reason == "invalid_instructions":
            return (
                "Let's practice with mathematically correct problems. "
                "Tell me which operations or number range you'd like to use."
                )
        return generation_fallback(UnsupportedProblemRequest(reason=decision.reason))
    if decision.reason == "answer_without_problem":
        return messages.NO_PROBLEM
    return (
        "I'm not sure what you'd like to practice. Try asking: "
        "'Give me an easy addition problem with numbers below 20.'"
        )


def _log_failure(error: AIProviderError) -> None:
    """Log failure categories and safe diagnostics without SDK exception payloads."""
    if isinstance(error, AIServiceUnavailable):
        logger.warning("Problem generation failed: category=%s reason=%s status=%s",
                       type(error).__name__, error.reason, error.status_code)
    elif isinstance(error, UnsupportedProblemRequest):
        logger.warning("Problem generation failed: category=%s reason=%s",
                       type(error).__name__, error.reason)
    elif isinstance(error, GenerationExhausted):
        logger.warning("Problem generation failed: category=%s attempts=%s last_failure=%s issues=%s",
                       type(error).__name__, error.attempts, type(error.last_failure).__name__,
                       ", ".join(issue.code for issue in error.last_failure.issues))
    elif isinstance(error, (GeneratedProblemInvalid, RequestInterpretationInvalid)):
        logger.warning("Problem generation failed: category=%s issues=%s", type(error).__name__,
                       "; ".join(f"{issue.code}: {issue.message}" for issue in error.issues))
    else:
        logger.warning("Problem generation failed: category=%s", type(error).__name__)


def _candidate_details(problem) -> str:
    """Format a candidate's statement and mathematical metadata for development inspection."""
    return (
        f"Expression: {problem.expression}\n"
        f"Application answer: {getattr(problem, 'answer', 'not supplied')}\n"
        f"Application operations: {', '.join(getattr(problem, 'operations', ())) or 'not supplied'}\n"
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


async def _send_development_data(
        message, 
        rejections: list[GenerationRejection],
        result: ValidatedProblem | None = None,
        ) -> None:
    """Send bounded inspection messages for rejected and verified candidates."""
    for rejection in rejections:
        details = (
            f"[Development data - REJECTED, attempt {rejection.attempt}]\n"
            f"Category: {type(rejection.error).__name__}\n"
            + "\n".join(
                f"{issue.code}: {issue.message}" for issue in rejection.error.issues
                )
            )
        details += "\n" + _request_details(rejection)
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
            "Checks: arithmetic and compiled requirements passed.\n"
            + _request_details(result) + "\n"
            + _candidate_details(result.problem)
            + "\n" + _solution_details(result.analysis)
            )
        await message.reply_text(details[:4000], parse_mode=None)


def _request_details(record) -> str:
    """Render interpreted requirements, effective limits, and story review status."""
    lines = []
    diagnostics = record.request_diagnostics
    if diagnostics is not None:
        if "interpreted" in diagnostics:
            lines.append("Interpreted requirements: " + json.dumps(diagnostics["interpreted"], ensure_ascii=False)[:950])
        lines.append("Difficulty preset: " + str(diagnostics.get("preset", "unspecified")))
        if diagnostics.get("preferred_operations") is not None:
            lines.append("Preferred operation count: " + str(diagnostics["preferred_operations"]))
        lines.append("Explicit preferences: " + json.dumps(diagnostics.get("explicit", {}), ensure_ascii=False)[:700])
    policy = record.constraints
    if policy is not None:
        lines.extend([
            f"Effective operand range (inclusive): {policy.min_operand}..{policy.max_operand}",
            f"Allowed operators: {', '.join(policy.allowed_operations)}; required: {', '.join(policy.required_operations) or 'none'}",
            f"Operation count: {policy.min_operations}..{policy.max_operations}",
            f"Intermediate range (before final): {policy.min_intermediate_value}..{policy.max_intermediate_value}",
            f"Final range: {policy.min_final_value}..{policy.max_final_value}",
        ])
    review = record.story_review
    if review is None:
        lines.append("Story review: not performed; calculations alone do not establish story agreement.")
    else:
        lines.extend([
            "Story review (model assessment): "
            f"story={review.has_story}, question={review.has_question}, "
            f"ambiguous={review.ambiguous}, consistent={review.consistent_quantities}",
            f"Review attempts: {record.story_review_attempts}; disclosed results: {json.dumps(review.disclosed_results, ensure_ascii=False)}",
            f"Story calculation: {review.expression}",
            ])
    return "\n".join(lines)


def _session_key(update: Update) -> tuple[int, int]:
    """Identify the conversation and learner for independent coach state."""
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "effective_message", None)
    return (getattr(chat, "id", getattr(message, "chat_id", 0)), getattr(user, "id", 0))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset this conversation and invite a new arithmetic request."""
    message = update.effective_message
    if message is None:
        return
    user = getattr(update, "effective_user", None)
    first_name = user.first_name if user else "there"
    await message.reply_text(
        f"Hello, {first_name}. I'm Matheutic.\n\n"
        "Describe the kind of arithmetic problem you'd like."
        )
    if context is not None:
        store = context.bot_data.setdefault("session_store", InMemorySessionStore())
        store.reset(_session_key(update))
        logger.info("Coach session reset: state=IDLE")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deliver a coach reply and commit the resulting conversation state."""
    message = update.effective_message
    if message is None or not message.text:
        return
    provider = context.bot_data["ai_provider"]
    dev_mode = context.bot_data.get("dev_mode", False)
    store = context.bot_data.setdefault("session_store", InMemorySessionStore())
    key = _session_key(update)
    saved = store.get(key)
    session = deepcopy(saved)
    coach = Coach(provider, context.bot_data.get("problem_constraints"), dev_mode=dev_mode,
                  max_attempts=context.bot_data.get("max_generation_attempts", MAX_GEN_ATTEMPTS))
    coach.calculation_selector = context.bot_data.get("calculation_selector")
    rejections: list[GenerationRejection] | None = [] if dev_mode else None
    try:
        reply = await coach.handle(
            session, message.text,
            on_rejection=rejections.append if rejections is not None else None,
            )
    except AIProviderError as error:
        _log_failure(error)
        logger.info("Coach turn failed: state=%s preserved", saved.state.value)
        fallback = (
            "I couldn't understand that message reliably. Try an answer, ask for a hint, "
            "or request another problem." 
            if saved.active and isinstance(error, RequestInterpretationInvalid)
            else generation_fallback(error)
            )
        await message.reply_text(fallback)
        if rejections is not None:
            await _send_development_data(message, rejections)
        return
    text = request_reply(reply.route, active=session.active) if reply.route is not None else reply.text
    if reply.reaction is not None:
        try:
            await message.set_reaction(reaction=reply.reaction)
        except Exception as error:
            logger.warning("Acknowledgement reaction failed: category=%s", type(error).__name__)
            text = messages.ACKNOWLEDGEMENT
            await message.reply_text(text)
    else:
        await message.reply_text(text)
    if session.run is not None:
        session.run.remember("learner", message.text)
        session.run.remember("coach", text or messages.ACKNOWLEDGEMENT)
    store.save(key, session)
    run = session.run
    logger.info(
        "Coach turn: intent=%s state=%s->%s attempts=%s final_attempts=%s hints_used=%s hint_level=%s step=%s outcome=%s pending_difficulty=%s",
        reply.intent, saved.state.value, session.state.value,
        run.attempts if run else 0, run.final_attempts if run else 0,
        run.hints_used if run else 0, run.hint_level if run else 0,
        run.step_index + 1 if run and run.step_index is not None else "final",
        run.outcome if run else None,
        session.pending_difficulty.kind if session.pending_difficulty is not None else None)
    if rejections is not None:
        await _send_development_data(message, rejections, reply.generated)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Report unexpected handler failures with a safe learner-facing fallback."""
    error = context.error
    logger.error("Unhandled Telegram handler failure: category=%s", type(error).__name__)
    message = getattr(update, "effective_message", None)
    if message is None:
        return
    text = (generation_fallback(error) if isinstance(error, AIProviderError) else
            "Something went wrong while handling your request. Please try again.")
    try:
        await message.reply_text(text)
    except Exception as delivery_error:
        logger.warning("Fallback delivery failed: category=%s", type(delivery_error).__name__)


def create_application(
        token: str, 
        provider: AIProvider,
        constraints: ProblemConstraints | None = None, 
        *,
        dev_mode: bool = False, 
        max_generation_attempts: int = MAX_GEN_ATTEMPTS,
        ) -> Application:
    """Build a polling application with a validation policy and optional development output."""
    generator = ProblemGenerator(
        provider, constraints, max_attempts=max_generation_attempts, dev_mode=dev_mode,
        )
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    application = Application.builder().token(token).concurrent_updates(False).build()
    application.bot_data.update({
        "ai_provider": provider,
        "problem_constraints": generator.constraints,
        "max_generation_attempts": generator.max_attempts,
        "dev_mode": dev_mode,
        "session_store": InMemorySessionStore(),
        })
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    application.add_error_handler(handle_error)
    return application


def main() -> None:
    """Load settings and run Telegram long polling with optional development diagnostics."""
    parser = argparse.ArgumentParser(description="Run the Matheutic Telegram coach.")
    parser.add_argument("--dev", action=argparse.BooleanOptionalAction, default=None,
                        help="Display development data and log model token usage (default: off).")
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
