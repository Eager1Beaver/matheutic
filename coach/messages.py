"""Fixed learner-facing feedback and practice invitations."""
import random

# TODO: to be localized
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
