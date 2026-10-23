"""Learner-scoped adaptive evidence and transactional recommendation records."""
from __future__ import annotations

from fractions import Fraction
import json

from adaptive.models import (
    AdaptiveState, AttemptFact, EvidenceSnapshot, FeedbackRecorded, PlanActivated,
    PracticeProposal, ProblemObservation, ProposalOffered, ProposalResponded,
)
from config import adaptive as settings
from core.constraints import ProblemConstraints
from core.expression import analyze_expression

from .codec import _request, json_text, request_data
from .errors import SessionConflict, StateRecoveryError


def read_request(raw):
    try:
        return _request(json.loads(raw)) if raw is not None else None
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise StateRecoveryError("Saved adaptive target failed validation") from error


class AdaptiveRepository:
    """Read factual snapshots and save adaptive effects in the learner transaction."""

    def _adaptive_context(self, connection, user_id, session):
        row = connection.execute("SELECT * FROM adaptive_state WHERE user_id = ?", (user_id,)).fetchone()
        try:
            state = AdaptiveState() if row is None else AdaptiveState(
                read_request(row["plan_json"]), row["variant"], row["proposal_id"], row["revision"],
                row["activation_count"], row["last_offer_count"], json.loads(row["feedback_json"]),
            )
            if not isinstance(state.feedback, dict):
                raise ValueError("Invalid practice feedback")
            proposal = None
            if session.pending_proposal_id is not None:
                record = connection.execute(
                    "SELECT * FROM practice_proposals WHERE id = ? AND user_id = ? AND status = 'offered'",
                    (session.pending_proposal_id, user_id),
                ).fetchone()
                if record is None:
                    raise ValueError("Missing practice proposal")
                proposal = PracticeProposal(record["id"], record["action"], record["reason"], read_request(record["baseline_json"]),
                                            read_request(record["target_json"]), json.loads(record["evidence_json"]), record["policy_version"])
                if proposal.baseline is None or proposal.target is None:
                    raise ValueError("Missing proposal target")
            return state, proposal
        except (ValueError, TypeError, KeyError) as error:
            raise StateRecoveryError("Saved recommendation state failed validation") from error

    def _check_pending(self, connection, session_id, session):
        if session.pending_proposal_id is None:
            return
        row = connection.execute(
            "SELECT 1 FROM practice_proposals pp JOIN sessions s ON s.id = pp.session_id "
            "WHERE pp.id = ? AND pp.session_id = ? AND pp.status = 'offered' AND pp.user_id = s.user_id",
            (session.pending_proposal_id, session_id),
        ).fetchone()
        if row is None:
            raise StateRecoveryError("Saved practice disagrees with its pending recommendation")

    def _apply_adaptive(self, connection, user_id, session_id, turn):
        if turn.reset:
            connection.execute("UPDATE practice_proposals SET status = 'expired', responded_at = ? WHERE user_id = ? AND status = 'offered'",
                               (turn.metadata.delivered_at, user_id))
        if not turn.adaptive_effects:
            return
        connection.execute("INSERT OR IGNORE INTO adaptive_state(user_id) VALUES (?)", (user_id,))
        revision = connection.execute("SELECT revision FROM adaptive_state WHERE user_id = ?", (user_id,)).fetchone()[0]
        if revision != turn.context.adaptive_state.revision:
            raise SessionConflict("The adaptive plan changed before this turn was saved")
        for effect in turn.adaptive_effects:
            if isinstance(effect, ProposalOffered):
                p = effect.proposal
                connection.execute(
                    "INSERT INTO practice_proposals(id, user_id, session_id, trigger_problem_id, action, reason, baseline_json, "
                    "target_json, evidence_json, policy_version, offered_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'offered')",
                    (p.id, user_id, session_id, effect.trigger_problem_id, p.action, p.reason, json_text(request_data(p.baseline)),
                     json_text(request_data(p.target)), json_text(p.evidence), p.policy_version, turn.metadata.delivered_at),
                )
                connection.execute("UPDATE adaptive_state SET last_offer_count = ? WHERE user_id = ?", (effect.assessable_count, user_id))
            elif isinstance(effect, ProposalResponded):
                if effect.status not in {"accepted", "declined", "expired", "superseded"}:
                    raise ValueError("Invalid recommendation response")
                if effect.problem_id is not None and connection.execute(
                    "SELECT 1 FROM problems WHERE id = ? AND session_id = ?", (effect.problem_id, session_id),
                ).fetchone() is None:
                    raise SessionConflict("The applied problem is not owned by this session")
                changed = connection.execute(
                    "UPDATE practice_proposals SET status = ?, responded_at = ?, first_problem_id = ? "
                    "WHERE id = ? AND user_id = ? AND session_id = ? AND status = 'offered'",
                    (effect.status, turn.metadata.delivered_at, effect.problem_id, effect.proposal_id, user_id, session_id),
                ).rowcount
                if changed != 1:
                    raise SessionConflict("The recommendation is no longer available")
            elif isinstance(effect, PlanActivated):
                if effect.variant not in {"standard", "foundation_support"}:
                    raise ValueError("Invalid practice variant")
                if effect.proposal_id is not None and connection.execute(
                    "SELECT 1 FROM practice_proposals WHERE id = ? AND user_id = ? AND status = 'accepted' AND first_problem_id IS NOT NULL",
                    (effect.proposal_id, user_id),
                ).fetchone() is None:
                    raise SessionConflict("An adaptive target needs an accepted, applied proposal")
                connection.execute(
                    "UPDATE adaptive_state SET plan_json = ?, variant = ?, proposal_id = ?, revision = revision + 1, activation_count = ? WHERE user_id = ?",
                    (json_text(request_data(effect.request)), effect.variant, effect.proposal_id, effect.assessable_count, user_id),
                )
            elif isinstance(effect, FeedbackRecorded):
                if effect.operation not in {"+", "-", "*", "/"} or effect.comfort not in {"needs_support", "comfortable"}:
                    raise ValueError("Invalid learner practice feedback")
                feedback = json.loads(connection.execute("SELECT feedback_json FROM adaptive_state WHERE user_id = ?", (user_id,)).fetchone()[0])
                feedback[effect.operation] = {"comfort": effect.comfort, "reported_at": turn.metadata.received_at}
                connection.execute("UPDATE adaptive_state SET feedback_json = ? WHERE user_id = ?", (json_text(feedback), user_id))
            else:
                raise TypeError("Unknown adaptive effect")

    async def learner_evidence(self, telegram_user_id: int, current_problem_id: str | None = None) -> EvidenceSnapshot:
        """Read distinct counts and filtered, bounded history in a consistent snapshot."""
        return await self._call(self._learner_evidence, telegram_user_id, current_problem_id)

    def _observation(self, connection, row):
        attempts = tuple(AttemptFact(Fraction(int(a["value_numerator"]), int(a["value_denominator"])), a["step_index"],
                                     bool(a["is_final"]), bool(a["correct"]), a["hints_used_before"])
                         for a in connection.execute("SELECT * FROM attempts WHERE problem_id = ? ORDER BY sequence", (row["id"],)))
        hints = connection.execute("SELECT COALESCE(SUM(consumes_hint), 0) FROM hints WHERE problem_id = ?", (row["id"],)).fetchone()[0]
        return ProblemObservation(row["id"], row["difficulty"], ProblemConstraints(**json.loads(row["constraints_json"])),
                                  analyze_expression(row["expression"]), row["status"], row["end_reason"], attempts, hints,
                                  json.loads(row["selection_metadata_json"]), row["finished_at"] or "")

    def _learner_evidence(self, telegram_user_id, current_problem_id):
        connection = self._db()
        owned = " FROM problems p JOIN sessions s ON s.id = p.session_id JOIN users u ON u.id = s.user_id WHERE u.telegram_user_id = ? "
        attempted = "EXISTS (SELECT 1 FROM attempts a WHERE a.problem_id = p.id)"
        eligible = "p.status != 'active' AND p.end_reason NOT IN ('stopped', 'session_reset') AND " + attempted
        connection.execute("BEGIN")
        try:
            counts = connection.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN " + eligible + " THEN 1 ELSE 0 END), 0)" + owned + " AND " + attempted,
                                        (telegram_user_id,)).fetchone()
            rows = list(connection.execute("SELECT p.*" + owned + " AND " + eligible + " ORDER BY p.finished_at DESC, p.id DESC LIMIT ?",
                                           (telegram_user_id, settings.HISTORY_WINDOW_PROBLEMS)))
            known = {row["id"] for row in rows}
            for operation in ("*", "/"):
                for row in connection.execute(
                    "SELECT p.*" + owned + " AND " + eligible + " AND EXISTS (SELECT 1 FROM problem_operations po "
                    "WHERE po.problem_id = p.id AND po.operation = ?) ORDER BY p.finished_at DESC, p.id DESC LIMIT ?",
                    (telegram_user_id, operation, settings.HISTORY_WINDOW_PROBLEMS),
                ):
                    if row["id"] not in known:
                        rows.append(row)
                        known.add(row["id"])
            rows.sort(key=lambda r: (r["finished_at"], r["id"]), reverse=True)
            current = connection.execute("SELECT p.*" + owned + " AND p.id = ?", (telegram_user_id, current_problem_id)).fetchone()
            result = EvidenceSnapshot(counts[0], counts[1], tuple(self._observation(connection, r) for r in rows),
                                      self._observation(connection, current) if current is not None else None)
            connection.execute("COMMIT")
            return result
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
