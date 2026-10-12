"""Coach actions, verified answer progression, and bounded problem generation."""
from __future__ import annotations

from dataclasses import dataclass

from ai.coach import CoachDecision, CoachInterpreter
from ai.errors import GenerationExhausted
from ai.intent import RequestDecision, compile_decision
from ai.orchestrator import GenerationRejection, ProblemGenerator, ValidatedProblem
from ai.provider import AIProvider
from core.constraints import ProblemConstraints

from . import messages
from .hints import plan_hint, render_hint, solution_text
from .session import (
    AnswerAttempt,
    CoachSession,
    CoachState,
    ProblemRun,
)


@dataclass(frozen=True)
class CoachReply:
    intent: str
    text: str | None = None
    reaction: str | None = None
    route: RequestDecision | None = None
    generated: ValidatedProblem | None = None


class Coach:
    """Apply contextual learner actions to a caller-owned working session."""

    def __init__(
            self, 
            provider: AIProvider, 
            constraints: ProblemConstraints | None = None, 
            *, 
            max_attempts: int = 3, 
            dev_mode: bool = False,
            ) -> None:
        self.provider = provider
        self.calculation_selector = None
        self.interpreter = CoachInterpreter(provider, constraints, dev_mode=dev_mode)
        self.max_attempts = max_attempts
        self.dev_mode = dev_mode

    async def handle(self, session: CoachSession, text: str, *, on_rejection=None) -> CoachReply:
        """Interpret a turn and update state for a reply awaiting delivery."""
        decision = await self.interpreter.interpret(text, session)
        intent = decision.intent
        if intent in {"generate_problem", "repeat_problem"}:
            return await self._generate(session, decision, on_rejection)
        if intent == "answer":
            return self._answer(session, decision)
        if intent == "continue":
            if session.state == CoachState.OFFERING_HINT:
                return await self._hint(session, intent)
            if session.state == CoachState.PROBLEM_COMPLETE:
                return await self._generate(session, CoachDecision("repeat_problem"), on_rejection)
            return CoachReply(intent, messages.UNCLEAR if session.active else messages.NO_PROBLEM)
        if intent == "decline":
            if session.state == CoachState.OFFERING_HINT:
                session.state = CoachState.AWAITING_ANSWER
                return CoachReply(intent, messages.DECLINE_HINT)
            if session.state == CoachState.PROBLEM_COMPLETE:
                session.state = CoachState.IDLE
                return CoachReply(intent, reaction="👍")
            return CoachReply(intent, messages.UNCLEAR if session.active else messages.ACKNOWLEDGEMENT)
        if intent == "stop":
            if session.active:
                session.run.outcome = "stopped"
            session.state = CoachState.IDLE
            return CoachReply(intent, reaction="👍")
        if intent == "give_up":
            if not session.active:
                return CoachReply(intent, messages.NO_PROBLEM)
            session.run.outcome = "revealed"
            session.state = CoachState.PROBLEM_COMPLETE
            return CoachReply(intent, f"{solution_text(session.run)}\n\n{messages.NEXT_PROBLEM}")
        if intent in {"request_hint", "repeat_hint", "explain"}:
            if intent == "explain" and session.state == CoachState.PROBLEM_COMPLETE:
                return CoachReply(intent, solution_text(session.run))
            return await self._hint(session, intent, question=text if intent == "explain" else "")
        route = decision.request or RequestDecision(intent, decision.reason)
        if intent == "clarify" and session.active:
            return CoachReply(intent, messages.UNCLEAR)
        return CoachReply(intent, route=route)

    async def _generate(self, session: CoachSession, decision: CoachDecision, on_rejection) -> CoachReply:
        """Generate a replacement before changing the current problem record."""
        request = decision.request if decision.intent == "generate_problem" else session.repeat_request
        if request is None:
            from ai.schemas import ProblemRequest, RequestInterpretation
            request = compile_decision(RequestInterpretation(
                intent="generate_problem", reason="none", 
                problem_request=ProblemRequest(
                    allowed_operations=None, required_operations=[], min_operand=None, max_operand=None,
                    min_operations=None, max_operations=None, min_intermediate_value=None,
                    max_intermediate_value=None, min_final_value=None, max_final_value=None,
                    difficulty=None, difficulty_change=0, inherit_previous=False, unresolved=False,
                    clear_limits=[], language="en", theme="", style="",
                    )
                    ), 
                    self.interpreter.constraints,
                    )
        if request.intent != "generate_problem":
            return CoachReply(decision.intent, route=request)
        from coach.calculations import select_calculation
        try:
            plan = (self.calculation_selector or select_calculation)(request.constraints)
        except GenerationExhausted as error:
            if on_rejection is not None:
                on_rejection(GenerationRejection(
                    error.attempts, 
                    error.last_failure,
                    constraints=request.constraints, 
                    request_diagnostics=request.diagnostics,
                    ))
            raise
        generator = ProblemGenerator(
            self.provider, 
            request.constraints, 
            difficulty=request.difficulty,
            max_attempts=self.max_attempts, 
            dev_mode=self.dev_mode,
            review_story=True,
            request_diagnostics=request.diagnostics,
            calculation=plan,
            )
        result = await generator.generate(request.generation_request, request.language, on_rejection=on_rejection)
        if session.active:
            session.run.outcome = "replaced"
        session.run = ProblemRun(result)
        session.state = CoachState.AWAITING_ANSWER
        session.difficulty = getattr(result.problem, "difficulty", request.difficulty)
        session.language = request.language
        session.repeat_request = request
        return CoachReply(decision.intent, result.problem.statement, generated=result)

    def _answer(self, session: CoachSession, decision: CoachDecision) -> CoachReply:
        """Grade the submitted value against the final or selected step result."""
        if not session.active:
            return CoachReply("answer", messages.NO_PROBLEM)
        run = session.run
        target = None if decision.final_answer else run.step_index
        expected = run.validated.analysis.value if target is None else run.validated.analysis.steps[target].result
        correct = decision.value == expected
        final = target is None or target == len(run.validated.analysis.steps) - 1
        run.attempts += 1
        run.final_attempts += int(final)
        run.recent_attempts.append(AnswerAttempt(decision.value, target, correct))
        if not correct:
            session.state = CoachState.OFFERING_HINT
            return CoachReply("answer", messages.OFFER_HINT)
        if final:
            run.outcome = "solved"
            session.state = CoachState.PROBLEM_COMPLETE
            if target is not None:
                run.steps_solved = target + 1
            return CoachReply("answer", messages.completion_reply())
        run.steps_solved = target + 1
        run.step_index = target + 1
        run.hint_level = 0
        run.last_hint = None
        session.state = CoachState.AWAITING_ANSWER
        step = run.validated.analysis.steps[run.step_index]
        return CoachReply(
            "answer", 
            f"That's right for that step.\n\nStep {run.step_index + 1} of {len(run.validated.analysis.steps)}: "
            f"work out {step.left} {step.operation} {step.right}. What is this step's result?"
            )

    async def _hint(self, session: CoachSession, intent: str, *, question: str = "") -> CoachReply:
        """Deliver progressive guidance or repeat it without consuming another level."""
        if not session.active:
            return CoachReply(intent, messages.NO_PROBLEM)
        run = session.run
        if intent == "repeat_hint" and run.last_hint:
            session.state = CoachState.AWAITING_ANSWER
            return CoachReply(intent, run.last_hint)
        repeat = intent == "explain" and run.hint_level > 0
        plan = plan_hint(run, repeat=repeat)
        if plan is None:
            return CoachReply(intent, messages.HINT_LIMIT)
        text = await render_hint(self.provider, run, plan, language=session.language, dev_mode=self.dev_mode, question=question)
        if not repeat:
            run.hints_used += 1
        run.hint_level = plan.level
        run.step_index = plan.step_index
        run.last_hint = text
        session.state = CoachState.AWAITING_ANSWER
        return CoachReply(intent, text)
