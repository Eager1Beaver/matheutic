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


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = update.effective_user
    first_name = user.first_name if user else "there"

    await update.message.reply_text(
        f"Hello, {first_name}. Matheutic is online.\n\n"
        "For now, I simply echo any text message you send me."
    )


async def echo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message and update.message.text:
        await update.message.reply_text(
            f"You said: {update.message.text}"
        )


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
            echo,
        )
    )

    logger.info("Bot is running. Press Ctrl+C to stop.")

    application.run_polling()


if __name__ == "__main__":
    main()