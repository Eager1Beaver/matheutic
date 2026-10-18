"""Delivered-turn retries and conversation loading for the Telegram adapter."""
from __future__ import annotations

import asyncio
import logging
from copy import deepcopy

from .errors import DatabaseUnavailable
from .models import DeliveredTurn
from .repository import SQLiteRepository

logger = logging.getLogger(__name__)


class PracticeStore:
    """Retain a delivered turn until it is committed before allowing more practice."""

    def __init__(self, repository: SQLiteRepository) -> None:
        self.repository = repository
        self.pending: DeliveredTurn | None = None

    async def open(self) -> None:
        """Prepare storage before handling learner messages."""
        try:
            await self.repository.open()
        except BaseException:
            await self.repository.close()
            raise

    async def load(self, telegram_user_id, chat_id, update_id=None, *, reset=False):
        """Recover pending writes before loading the next conversation turn."""
        await self.flush()
        return await self.repository.load(telegram_user_id, chat_id, update_id, reset=reset)

    async def commit(self, turn: DeliveredTurn) -> None:
        """Retain an immutable working copy and attempt to save its delivered effects."""
        await self.flush()
        self.pending = deepcopy(turn)
        await self.flush()

    async def flush(self) -> None:
        """Retry a pending transaction with bounded asynchronous backoff."""
        if self.pending is None:
            return
        for attempt, delay in enumerate((0, 0.05, 0.2), 1):
            if delay:
                await asyncio.sleep(delay)
            try:
                await self.repository.commit(self.pending)
            except DatabaseUnavailable:
                logger.warning("Learner progress save unavailable: attempt=%s", attempt)
                if attempt == 3:
                    raise
            else:
                self.pending = None
                return

    async def close(self) -> None:
        """Attempt outstanding writes before releasing the database worker."""
        try:
            await self.flush()
        finally:
            await self.repository.close()
