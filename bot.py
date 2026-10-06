"""Telegram handlers for presenting mathematically validated arithmetic problems."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    )

from ai.groq_provider import GroqProvider
from ai.provider import AIProvider, AIProviderError
from core.constraints import ProblemConstraints
from core.problem_validator import ProblemValidationError, validate_problem

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import (
        ContextTypes,
        )

logger = logging.getLogger(__name__)


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
    """Generate a candidate and present its statement only after validation."""
    message = update.effective_message
    if message is None or not message.text:
        return
    
    provider: AIProvider = context.bot_data["ai_provider"]
    constraints = context.bot_data.get("problem_constraints", ProblemConstraints())
    
    try:
        problem = await provider.generate_problem(request=message.text, language="en")
        analysis = validate_problem(problem, constraints)
    # TODO: Distinguish unsupported requests, invalid generations, and provider failures.
    except AIProviderError:
        logger.exception("Problem generation failed.")
        await message.reply_text("I couldn't generate a problem right now. Please try again.")
        return
    except ProblemValidationError as error:
        logger.warning("Rejected arithmetic candidate: %s", ", ".join(issue.code for issue in error.issues))
        await message.reply_text("I couldn't generate a valid arithmetic problem. Please try again.")
        return
    
    logger.debug("Validated arithmetic: result=%s operations=%s", analysis.value, analysis.operations)
    #await message.reply_text(problem.statement)

    logger.info(
        "Generated MathProblem: %s",
        problem.model_dump_json(),
    )

    await update.message.reply_text(
        f"{problem.statement}\n\n"
        f"[Development data]\n"
        f"Expression: {problem.expression}\n"
        f"Answer: {problem.answer}\n"
        f"Operations: {', '.join(problem.operations)}\n"
        f"Difficulty: {problem.difficulty}\n"
        f"Language: {problem.language}"
    )


def create_application(
        token: str, 
        provider: AIProvider, 
        constraints: ProblemConstraints | None = None,
        ) -> Application:
    """Build a polling application with its provider and validation constraints."""
    if constraints is not None and not isinstance(constraints, ProblemConstraints):
        raise TypeError("constraints must be ProblemConstraints")
    

    application = Application.builder().token(token).build()
    application.bot_data["ai_provider"] = provider
    application.bot_data["problem_constraints"] = ProblemConstraints() if constraints is None else constraints
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    return application


def main() -> None:
    """Load credentials, configure logging, and run Telegram long polling."""

    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to your .env file.")
    
    logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    application = create_application(token, GroqProvider())
    logger.info("Bot is running. Press Ctrl+C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()
