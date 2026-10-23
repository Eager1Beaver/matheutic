"""Atomic learner sessions, complete learning history, and practice observations."""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
from fractions import Fraction

from coach.events import AttemptMade, HintShown, ProblemEnded, ProblemStarted
from coach.session import CoachSession
from config.preferences import UserPreferences

from .codec import decode_session, encode_session, exact, json_text
from .database import SQLiteDatabase
from .errors import SessionConflict, StateRecoveryError
from .models import DeliveredTurn, LearnerContext, ObservationWindow, utc_now
from .adaptive import AdaptiveRepository

logger = logging.getLogger(__name__)


class SQLiteRepository(AdaptiveRepository, SQLiteDatabase):
    """Persist delivered turns for one bot, retaining learner and chat identity."""

    def __init__(self, path, *, preferences: UserPreferences | None = None, timeout: float = 0.25) -> None:
        super().__init__(path, timeout=timeout)
        self.initial_preferences = preferences or UserPreferences()

    async def load(self, telegram_user_id: int, chat_id: int, update_id: int | None = None, *, reset: bool = False) -> LearnerContext:
        """Load a learner's open session without exposing another chat's checkpoint."""
        if type(telegram_user_id) is not int or telegram_user_id <= 0 or type(chat_id) is not int or chat_id == 0:
            raise ValueError("A Telegram learner and conversation are required")
        return await self._call(self._load, telegram_user_id, chat_id, update_id, reset)

    def _preferences(self, connection, user_id: int | None) -> UserPreferences:
        row = connection.execute("SELECT interface_language, content_language FROM user_preferences WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return self.initial_preferences
        try:
            return UserPreferences(**dict(row))
        except ValueError as error:
            raise StateRecoveryError("Saved language preferences failed validation") from error

    def _load(self, telegram_user_id, chat_id, update_id, reset):
        connection = self._db()
        duplicate = update_id is not None and connection.execute("SELECT 1 FROM processed_updates WHERE update_id = ?", (update_id,)).fetchone() is not None
        user = connection.execute("SELECT id FROM users WHERE telegram_user_id = ?", (telegram_user_id,)).fetchone()
        user_id = user[0] if user is not None else None
        preferences = self._preferences(connection, user_id)
        row = connection.execute("SELECT * FROM sessions WHERE user_id = ? AND closed_at IS NULL", (user_id,)).fetchone()
        session = CoachSession(language=preferences.content_language)
        
        if row is not None and row["chat_id"] == chat_id and not duplicate and not reset:
            session = decode_session(row["coach_state_json"])
            try:
                self._check_history(connection, row["id"], session)
            except (ValueError, ZeroDivisionError) as error:
                raise StateRecoveryError("Saved problem history failed validation") from error
        
        adaptive_state, proposal = self._adaptive_context(connection, user_id, session)
        return LearnerContext(
            telegram_user_id, 
            chat_id, 
            user_id,
            row["id"] if row is not None else None,
            row["session_number"] if row is not None else None,
            row["chat_id"] if row is not None else None,
            row["revision"] if row is not None else 0,
            session, 
            preferences, 
            duplicate,
            row["last_prompt_at"] if row is not None else None,
            row["prompt_process_id"] if row is not None else None,
            row["prompt_kind"] if row is not None else None,
            adaptive_state, proposal,
            )

    def _check_history(self, connection, session_id: int, session: CoachSession) -> None:
        self._check_pending(connection, session_id, session)
        active = connection.execute("SELECT id FROM problems WHERE session_id = ? AND status = 'active'", (session_id,)).fetchone()
        run = session.run
        if run is None:
            if active is not None:
                raise StateRecoveryError("Saved practice is missing its active problem")
            return
        
        problem = connection.execute("SELECT * FROM problems WHERE id = ? AND session_id = ?", (run.problem_id, session_id)).fetchone()
        status = {None: "active", "solved": "solved", "revealed": "revealed", "stopped": "abandoned"}[run.outcome]
        
        if problem is None or problem["status"] != status or problem["expression"] != run.validated.problem.expression:
            raise StateRecoveryError("Saved practice disagrees with problem history")
        
        if problem["statement"] != run.validated.problem.statement or Fraction(int(problem["answer_numerator"]), int(problem["answer_denominator"])) != run.validated.analysis.value:
            raise StateRecoveryError("Saved problem content disagrees with its checkpoint")
        
        if (active is not None) != session.active or (active is not None and active[0] != run.problem_id):
            raise StateRecoveryError("Saved practice has inconsistent active problems")
        
        counts = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(is_final), 0) FROM attempts WHERE problem_id = ?", 
            (run.problem_id,),
            ).fetchone()
        hints = connection.execute(
            "SELECT COALESCE(SUM(consumes_hint), 0) FROM hints WHERE problem_id = ?", 
            (run.problem_id,)
            ).fetchone()[0]
        
        if tuple(counts) != (run.attempts, run.final_attempts) or hints != run.hints_used:
            raise StateRecoveryError("Saved practice counters disagree with learning history")

    async def commit(self, turn: DeliveredTurn) -> bool:
        """Commit one delivered reply and all of its learning effects atomically."""
        return await self._call(self._commit, turn)

    def _commit(self, turn: DeliveredTurn) -> bool:
        connection = self._db()
        checkpoint = encode_session(turn.session)
        decode_session(checkpoint)
        
        context, metadata = turn.context, turn.metadata
        if context.other_chat and not turn.reset:
            raise SessionConflict("Practice belongs to another conversation")
        
        connection.execute("BEGIN IMMEDIATE")
        try:
            if (
                metadata.update_id is not None 
                and connection.execute("SELECT 1 FROM processed_updates WHERE update_id = ?", (metadata.update_id,)).fetchone() is not None
                ):
                connection.execute("ROLLBACK")
                return False
            
            connection.execute(
                "INSERT INTO users(telegram_user_id, created_at, last_seen_at) VALUES (?, ?, ?) "
                "ON CONFLICT(telegram_user_id) DO UPDATE SET last_seen_at = excluded.last_seen_at",
                (context.telegram_user_id, metadata.delivered_at, metadata.received_at),
                )
            user_id = connection.execute("SELECT id FROM users WHERE telegram_user_id = ?", (context.telegram_user_id,)).fetchone()[0]
            current = connection.execute("SELECT id, revision FROM sessions WHERE user_id = ? AND closed_at IS NULL", (user_id,)).fetchone()
            if (
                   (current is None) != (context.session_id is None) 
                or (current is not None and tuple(current) != (context.session_id, context.revision))
                ):
                raise SessionConflict("The learner session changed before this turn was saved")
            
            connection.execute(
                "INSERT OR IGNORE INTO user_preferences(user_id, interface_language, content_language, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, context.preferences.interface_language, context.preferences.content_language, metadata.delivered_at),
                )
            if turn.reset and current is not None:
                connection.execute(
                    "UPDATE problems SET status = 'abandoned', end_reason = 'session_reset', finished_at = ? "
                    "WHERE session_id = ? AND status = 'active'", (metadata.delivered_at, current[0]),
                    )
                connection.execute(
                    "UPDATE sessions SET closed_at = ?, coach_state_json = ?, revision = revision + 1 WHERE id = ?",
                    (metadata.delivered_at, encode_session(CoachSession()), current[0]),
                    )
            if current is None or turn.reset:
                number = connection.execute("SELECT COALESCE(MAX(session_number), 0) + 1 FROM sessions WHERE user_id = ?", (user_id,)).fetchone()[0]
                cursor = connection.execute(
                    "INSERT INTO sessions(user_id, session_number, chat_id, started_at, start_reason, coach_state_json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, number, context.requested_chat_id, metadata.delivered_at, "start" if turn.reset else "implicit", checkpoint),
                    )
                session_id = cursor.lastrowid
            else:
                session_id = current[0]
            if metadata.update_id is not None:
                connection.execute(
                    "INSERT INTO processed_updates(update_id, user_id, session_id, received_at, message_at, committed_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (metadata.update_id, user_id, session_id, metadata.received_at, metadata.message_at, metadata.delivered_at),
                    )
            for event in turn.events:
                if isinstance(event, ProblemStarted):
                    self._start_problem(connection, session_id, event, metadata.delivered_at)
                elif isinstance(event, ProblemEnded):
                    changed = connection.execute(
                        "UPDATE problems SET status = ?, end_reason = ?, finished_at = ? WHERE id = ? AND session_id = ? AND status = 'active'",
                        (event.status, event.reason, metadata.delivered_at, event.problem_id, session_id),
                    ).rowcount
                    if changed != 1:
                        raise SessionConflict("A finished problem is not active in this session")
                elif isinstance(event, (AttemptMade, HintShown)):
                    if connection.execute("SELECT 1 FROM problems WHERE id = ? AND session_id = ? AND status = 'active'", (event.problem_id, session_id)).fetchone() is None:
                        raise SessionConflict("The learning event does not belong to an active problem")
                    if isinstance(event, AttemptMade):
                        self._attempt(connection, event, turn)
                    else:
                        self._hint(connection, event, metadata)
                else:
                    raise TypeError("Unknown learning event")
            
            if turn.reset:
                connection.execute(
                    "UPDATE sessions SET last_prompt_at = NULL, prompt_process_id = NULL, prompt_kind = NULL WHERE id = ?", 
                    (session_id,),
                    )
            if turn.prompt_kind is not None and turn.session.active:
                connection.execute(
                    "UPDATE sessions SET last_prompt_at = ?, prompt_process_id = ?, prompt_kind = ? WHERE id = ?",
                    (metadata.delivered_at, self.process_id, turn.prompt_kind, session_id),
                    )
            self._apply_adaptive(connection, user_id, session_id, turn)
            self._check_history(connection, session_id, turn.session)
            connection.execute("UPDATE sessions SET coach_state_json = ?, revision = revision + 1 WHERE id = ?", (checkpoint, session_id))
            connection.execute("COMMIT")
            logger.info(
                "Learner turn saved: session_id=%s events=%s reset=%s", 
                session_id, len(turn.events), turn.reset,
                )
            return True
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _start_problem(self, connection, session_id, event: ProblemStarted, presented_at):
        record, request = event.validated, event.request
        analysis = record.analysis
        number = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM problems WHERE session_id = ?", 
            (session_id,),
            ).fetchone()[0]
        actual = {
            "operands": analysis.operands,
            "intermediate_results": [exact(v) for v in analysis.intermediate_values[:-1]],
            "steps": [{
                "left": exact(s.left), 
                "operation": s.operation, 
                "right": exact(s.right), 
                "result": exact(s.result)} for s in analysis.steps],
                }
        connection.execute(
            "INSERT INTO problems(id, session_id, sequence, statement, expression, answer_numerator, answer_denominator, "
            "language, difficulty, configuration_version, operation_count, operand_min, operand_max, actual_json, "
            "explicit_preferences_json, interpreted_request_json, constraints_json, selection_source, presented_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')",
            (
                event.problem_id, session_id, 
                number, record.problem.statement, record.problem.expression,
                str(analysis.value.numerator), str(analysis.value.denominator), 
                record.problem.language, record.problem.difficulty,
                1, 
                len(analysis.operations), 
                min(analysis.operands), max(analysis.operands), 
                json_text(actual),
                json_text(request.preferences or {}), 
                json_text((request.diagnostics or {}).get("interpreted", {})),
                json_text(asdict(request.constraints)), 
                event.source, 
                presented_at,
                ),
                )
        connection.executemany(
            "INSERT INTO problem_operations(problem_id, operation, occurrences) VALUES (?, ?, ?)",
            [(event.problem_id, operation, count) for operation, count in Counter(analysis.operations).items()],
        )
        connection.execute("UPDATE problems SET selection_metadata_json = ? WHERE id = ?",
                           (json_text(event.selection_metadata), event.problem_id))

    def _timing(self, turn):
        context, metadata = turn.context, turn.metadata
        if context.last_prompt_at is None:
            return None, "missing_prompt"
        if context.prompt_process_id != self.process_id:
            return None, "restart"
        try:
            prompt = datetime.fromisoformat(context.last_prompt_at)
            received = datetime.fromisoformat(metadata.received_at)
            message = datetime.fromisoformat(metadata.message_at) if metadata.message_at is not None else None
            if received < prompt or (message is not None and message < prompt - timedelta(seconds=1)):
                return None, "before_prompt"
            return int((received - prompt).total_seconds() * 1000), "observed"
        except (ValueError, TypeError) as error:
            raise StateRecoveryError("Saved response timing failed validation") from error

    def _attempt(self, connection, event: AttemptMade, turn):
        number = connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM attempts WHERE problem_id = ?", (event.problem_id,)).fetchone()[0]
        response_ms, quality = self._timing(turn)
        metadata, context = turn.metadata, turn.context
        connection.execute(
            "INSERT INTO attempts(problem_id, sequence, value_numerator, value_denominator, expected_numerator, expected_denominator, "
            "step_index, is_final, correct, hints_used_before, operation, prompt_at, prompt_kind, message_at, received_at, feedback_at, "
            "response_ms, timing_quality, source_update_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.problem_id, 
                number, 
                str(event.value.numerator), str(event.value.denominator),
                str(event.expected.numerator), str(event.expected.denominator), 
                event.step_index, int(event.final), int(event.correct),
                event.hints_used, 
                event.operation, 
                context.last_prompt_at, context.prompt_kind, 
                metadata.message_at, metadata.received_at, metadata.delivered_at, 
                response_ms, 
                quality, 
                metadata.update_id,
                ),
                )

    def _hint(self, connection, event: HintShown, metadata):
        number = connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM hints WHERE problem_id = ?", (event.problem_id,)).fetchone()[0]
        connection.execute(
            "INSERT INTO hints(problem_id, sequence, kind, level, step_index, consumes_hint, presented_at, source_update_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.problem_id, 
                number, 
                event.kind, event.level, event.step_index, 
                int(event.consumes_hint), 
                metadata.delivered_at, metadata.update_id),
                )

    async def get_preferences(self, telegram_user_id: int) -> UserPreferences:
        """Return saved language settings or the configured initial defaults."""
        return await self._call(self._get_preferences, telegram_user_id)

    def _get_preferences(self, telegram_user_id):
        connection = self._db()
        row = connection.execute("SELECT id FROM users WHERE telegram_user_id = ?", (telegram_user_id,)).fetchone()
        return self._preferences(connection, row[0] if row is not None else None)

    async def set_preferences(self, telegram_user_id: int, preferences: UserPreferences) -> None:
        """Save explicit language settings without starting or resetting a session."""
        if type(telegram_user_id) is not int or telegram_user_id <= 0 or not isinstance(preferences, UserPreferences):
            raise ValueError("A learner identity and validated preferences are required")
        await self._call(self._set_preferences, telegram_user_id, preferences)

    def _set_preferences(self, telegram_user_id, preferences):
        connection = self._db()
        now = utc_now()
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("INSERT OR IGNORE INTO users(telegram_user_id, created_at, last_seen_at) VALUES (?, ?, ?)", (telegram_user_id, now, now))
            user_id = connection.execute("SELECT id FROM users WHERE telegram_user_id = ?", (telegram_user_id,)).fetchone()[0]
            connection.execute(
                "INSERT INTO user_preferences(user_id, interface_language, content_language, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET interface_language = excluded.interface_language, "
                "content_language = excluded.content_language, updated_at = excluded.updated_at",
                (user_id, preferences.interface_language, preferences.content_language, now),
                )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    async def recent_observations(self, telegram_user_id: int, *, limit: int = 10, operation: str | None = None) -> ObservationWindow:
        """Read recent delivered problems and factual performance across sessions."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Observation limit must be between 1 and 100")
        if operation not in {None, "+", "-", "*", "/"}:
            raise ValueError("Unknown practice operation")
        return await self._call(self._recent_observations, telegram_user_id, limit, operation)

    def _recent_observations(self, telegram_user_id, limit, operation):
        connection = self._db()
        rows = connection.execute(
            "SELECT p.*, s.session_number FROM problems p JOIN sessions s ON s.id = p.session_id "
            "JOIN users u ON u.id = s.user_id WHERE u.telegram_user_id = ? AND (? IS NULL OR EXISTS ("
            "SELECT 1 FROM problem_operations po WHERE po.problem_id = p.id AND po.operation = ?)) "
            "ORDER BY p.presented_at DESC, p.id DESC LIMIT ?", 
            (telegram_user_id, operation, operation, limit),
            ).fetchall()
        
        observations = []
        for row in rows:
            item = dict(row)
            item["answer"] = Fraction(int(item.pop("answer_numerator")), int(item.pop("answer_denominator")))
            for column, key in (
                ("actual_json", "actual"), 
                ("explicit_preferences_json", "preferences"),
                ("interpreted_request_json", "interpreted"), 
                ("constraints_json", "constraints"),
                ):
                item[key] = json.loads(item.pop(column))
            
            item["operations"] = dict(connection.execute(
                "SELECT operation, occurrences FROM problem_operations WHERE problem_id = ?", 
                (row["id"],),
                ))
            
            counts = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(is_final), 0), COALESCE(SUM(correct), 0) FROM attempts WHERE problem_id = ?", 
                (row["id"],),
                ).fetchone()
            item.update(zip(("attempts", "final_attempts", "correct_attempts"), counts))
            hints = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(consumes_hint), 0) FROM hints WHERE problem_id = ?", 
                (row["id"],),
                ).fetchone()
            item.update(zip(("hint_events", "hints_used"), hints))
            observations.append(item)
        return ObservationWindow(tuple(observations))

    async def problem_history(self, telegram_user_id: int, problem_id: str) -> dict | None:
        """Read one owned problem's attempts and hints without another learner's data."""
        return await self._call(self._problem_history, telegram_user_id, problem_id)

    def _problem_history(self, telegram_user_id, problem_id):
        connection = self._db()
        owned = connection.execute(
            "SELECT 1 FROM problems p JOIN sessions s ON s.id = p.session_id JOIN users u ON u.id = s.user_id "
            "WHERE p.id = ? AND u.telegram_user_id = ?", 
            (problem_id, telegram_user_id),
            ).fetchone()
        if owned is None:
            return None
        
        attempts = []
        for row in connection.execute(
            "SELECT * FROM attempts WHERE problem_id = ? ORDER BY sequence", 
            (problem_id,),
            ):
            item = dict(row)
            
            for prefix in ("value", "expected"):
                item[prefix] = Fraction(int(item.pop(prefix + "_numerator")), int(item.pop(prefix + "_denominator")))
            attempts.append(item)
        
        return {
            "attempts": attempts,
            "hints": [dict(row) for row in connection.execute(
                "SELECT * FROM hints WHERE problem_id = ? ORDER BY sequence", 
                (problem_id,),
                )],
                }
