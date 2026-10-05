import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ai.groq_provider import GroqProvider


load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is not set. "
        "Add it to your .env file."
    )


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

ai = GroqProvider()


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = update.effective_user
    first_name = user.first_name if user else "there"

    await update.message.reply_text(
        f"Hello, {first_name}. I'm Matheutic.\n\n"
        "For now, you can send me a message and I'll reply "
        "using an AI model."
    )


async def chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message or not update.message.text:
        return

    user_message = update.message.text

    logger.info(
        "Received message from Telegram user %s",
        update.effective_user.id
        if update.effective_user
        else "unknown",
    )

    try:
        response = await ai.reply(user_message)

    except RuntimeError:
        logger.exception("AI request failed.")

        await update.message.reply_text(
            "I couldn't generate a response right now. "
            "Please try again."
        )
        return

    await update.message.reply_text(response)


def main() -> None:
    logger.info("Starting Matheutic Telegram bot...")

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat,
        )
    )

    logger.info("Bot is running. Press Ctrl+C to stop.")

    application.run_polling()


if __name__ == "__main__":
    main()
