"""Application records for persisted learner turns and observations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from coach.events import LearningEvent
from coach.session import CoachSession
from config.preferences import UserPreferences


def utc_now() -> str:
    """Return the current UTC timestamp in the database's sortable format."""
    return datetime.now(UTC).isoformat(timespec="microseconds")


def timestamp(value: datetime) -> str:
    """Normalize an aware datetime to the database's UTC format."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timestamp must include a time zone")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class LearnerContext:
    telegram_user_id: int
    requested_chat_id: int
    user_id: int | None
    session_id: int | None
    session_number: int | None
    chat_id: int | None
    revision: int
    session: CoachSession
    preferences: UserPreferences
    duplicate: bool = False
    last_prompt_at: str | None = None
    prompt_process_id: str | None = None
    prompt_kind: str | None = None

    @property
    def other_chat(self) -> bool:
        """Whether practice belongs to a different conversation."""
        return self.chat_id is not None and self.chat_id != self.requested_chat_id


@dataclass(frozen=True)
class TurnMetadata:
    update_id: int | None
    received_at: str
    delivered_at: str
    message_at: str | None = None


@dataclass(frozen=True)
class DeliveredTurn:
    context: LearnerContext
    session: CoachSession
    events: tuple[LearningEvent, ...]
    metadata: TurnMetadata
    reset: bool = False
    prompt_kind: str | None = None


@dataclass(frozen=True)
class ObservationWindow:
    problems: tuple[dict, ...]

    @property
    def sample_count(self) -> int:
        """Return how many delivered problems are available in this window."""
        return len(self.problems)
