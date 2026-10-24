"""Fixed learner-facing feedback and practice invitations."""
import random

HELP = (
    "I'm Matheutic, your math practice coach.\n\n"
    "Ask me for the kind of math problem you'd like. You can choose the operations "
    "(addition, subtraction, multiplication, or division), number ranges, and difficulty. "
    "For example: 'Give me an addition problem with numbers below 20.' "
    "We work with non-negative integers only: whole numbers including zero, "
    "with no negative numbers or fractions.\n\n"
    "When you've solved a problem, send me your answer as a number or in words. "
    "If you need a hint, just ask, and we'll work through the problem together.\n\n"
    "As you practice, I'll be able to suggest problems that suit you better. "
    "You can always tell me what you'd like to practice."
    )

PRACTICE_IN_OTHER_CHAT = "Your practice is active in another chat. Use /start here to begin a new session in this chat."
PRACTICE_STORAGE_UNAVAILABLE = "I couldn't access your saved practice. Please wait a moment and try again."
PRACTICE_RECOVERY_FAILED = "I couldn't restore your saved practice safely. Use /start to begin a new session."

# TODO: to be localized
# TODO: include all user-facing messages in a single place - for example, here
PRAISE = ("That's right!", "Well done!", "Correct - nice work!")
NEXT_PROBLEM = "Would you like another problem?"
OFFER_HINT = "Not quite. Would you like a hint? You can also try another answer."
DECLINE_HINT = "Okay. Keep trying, and ask for a hint whenever you'd like one."
ACKNOWLEDGEMENT = "Okay. Come back whenever you'd like to practice."
NO_PROBLEM = "I don't have an active problem. Describe the kind of arithmetic problem you'd like."
UNCLEAR = "I didn't quite understand. You can try an answer, ask for a hint, or request another problem."
HINT_LIMIT = (
    "You've had all the hints for this step. Try an answer, ask me to repeat the hint, "
    "ask for the solution, or request another problem."
    )


def completion_reply() -> str:
    """Choose brief praise and invite another exercise."""
    return f"{random.choice(PRAISE)} {NEXT_PROBLEM}"
