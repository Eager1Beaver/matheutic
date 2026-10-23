"""Coach actions, verified answer progression, and bounded problem generation."""
from __future__ import annotations

from dataclasses import dataclass

from ai.coach import CoachDecision, CoachInterpreter
from ai.errors import GenerationExhausted
from ai.intent import (
    NUMERIC_FIELDS,
    RequestDecision,
    change_operators,
    compile_decision,
)
from ai.orchestrator import GenerationRejection, ProblemGenerator, ValidatedProblem
from ai.provider import AIProvider
from config.difficulty import MAX_PROGRESSIVE_DIFFICULTY, practice_preset
from core.constraints import ProblemConstraints

from . import messages
from .events import AttemptMade, HintShown, LearningEvent, ProblemEnded, ProblemStarted
from .hints import plan_hint, render_hint, solution_text
from .session import (
    AnswerAttempt,
    CoachSession,
    CoachState,
    DifficultyChoice,
    ProblemRun,
)


@dataclass(frozen=True)
class CoachReply:
    intent: str
    text: str | None = None
    reaction: str | None = None
    route: RequestDecision | None = None
    generated: ValidatedProblem | None = None
    events: tuple[LearningEvent, ...] = ()


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
        self.request_resolver = None
        self.dev_mode = dev_mode

    async def handle(self, session: CoachSession, text: str, *, on_rejection=None, decision: CoachDecision | None = None) -> CoachReply:
        """Interpret a turn and update state for a reply awaiting delivery."""
        pending_reply = await self._pending_choice(session, text, on_rejection)
        if pending_reply is not None:
            return pending_reply
        decision = decision or await self.interpreter.interpret(text, session)
        intent = decision.intent
        if session.pending_difficulty is not None and intent in {"continue", "decline"}:
            return await self._pending_choice(session, "yes" if intent == "continue" else "no", on_rejection)
        
        if intent in {"generate_problem", "repeat_problem"}:
            if (
                decision.request is not None 
                and decision.request.difficulty_change > 0
                and session.repeat_request is not None
                ):
                return await self._harder(session, decision.request, on_rejection)
            pending = session.pending_difficulty
            if (
                pending is not None 
                and decision.request is not None
                and decision.request.difficulty == pending.request.difficulty
                and decision.request.diagnostics["interpreted"]["allowed_operations"] is None
                ):
                choice = DifficultyChoice(
                    decision.request, 
                    "operators", 
                    pending.same_operations, 
                    pending.same_required,
                    )
                return await self._advance_choice(session, choice, on_rejection)
            return await self._generate(session, decision, on_rejection)
        
        if intent == "answer":
            session.pending_difficulty = None
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
            session.pending_difficulty = None
            events = ()
            if session.active:
                session.run.outcome = "stopped"
                events = (ProblemEnded(session.run.problem_id, "abandoned", "stopped"),)
            session.state = CoachState.IDLE
            return CoachReply(intent, reaction="👍", events=events)
        
        if intent == "give_up":
            session.pending_difficulty = None
            if not session.active:
                return CoachReply(intent, messages.NO_PROBLEM)
            session.run.outcome = "revealed"
            session.state = CoachState.PROBLEM_COMPLETE
            return CoachReply(intent, f"{solution_text(session.run)}\n\n{messages.NEXT_PROBLEM}", events=(
                ProblemEnded(session.run.problem_id, "revealed", "give_up"),
                ))
        
        if intent in {"request_hint", "repeat_hint", "explain"}:
            session.pending_difficulty = None
            if intent == "explain" and session.state == CoachState.PROBLEM_COMPLETE:
                return CoachReply(intent, solution_text(session.run))
            return await self._hint(session, intent, question=text if intent == "explain" else "")
        route = decision.request or RequestDecision(intent, decision.reason)
        
        if intent == "clarify" and session.active:
            return CoachReply(intent, messages.UNCLEAR)
        return CoachReply(intent, route=route)

    async def _harder(self, session: CoachSession, request: RequestDecision, on_rejection) -> CoachReply:
        """Confirm continuation choices while keeping the delivered exercise available."""
        if session.difficulty == MAX_PROGRESSIVE_DIFFICULTY:
            return CoachReply(
                "clarify", 
                "You've reached the largest automatic number range. You can specify custom limits or request another problem.",
                )
        previous = session.repeat_request.preferences or {}
        explicit_operators = session.practice_metadata.get(
            "explicit_operations", 
            "allowed_operations" in previous or bool(previous.get("required_operations"))
            )
        explicit = request.diagnostics["interpreted"]
        same = None
        if (
            explicit["allowed_operations"] is None 
            and not explicit["required_operations"]
            and explicit_operators
            ):
            same = session.repeat_request.constraints.allowed_operations
            if set(same) == set(request.constraints.allowed_operations):
                request = change_operators(request, self.interpreter.constraints, same, previous.get("required_operations", ()))
                same = None
        choice = DifficultyChoice(
            request, 
            "operators", 
            same, 
            tuple(previous.get("required_operations", ())),
            )
        if session.difficulty == 5 and not any(explicit[name] is not None for name in NUMERIC_FIELDS):
            choice.kind = "limits"
            session.pending_difficulty = choice
            policy = session.repeat_request.constraints
            next_maximum = practice_preset(request.difficulty).max_operand
            def result_range(lower, upper):
                return f"{lower or 0}..{upper}" if upper is not None else f"{lower or 0} or higher"
            return CoachReply(
                "clarify", 
                (
                    f"You're at difficulty 5: operands {policy.min_operand}..{policy.max_operand}, "
                    f"intermediate results {result_range(policy.min_intermediate_value, policy.max_intermediate_value)}, "
                    f"final answers {result_range(policy.min_final_value, policy.max_final_value)}, "
                    f"and {policy.min_operations}..{policy.max_operations} operations. "
                    "Would you like to specify custom limits? Send your limits or reply 'yes'. "
                    f"Reply 'no' to increase the default maximum values to {next_maximum}, keeping four operations."
                    ),
                    )
        return await self._advance_choice(session, choice, on_rejection)

    async def _advance_choice(self, session: CoachSession, choice: DifficultyChoice, on_rejection) -> CoachReply:
        """Ask about a changed operator set or generate the confirmed target request."""
        if choice.same_operations is not None and set(choice.same_operations) != set(choice.request.constraints.allowed_operations):
            choice.kind = "operators"
            session.pending_difficulty = choice
            names = {"+": "addition", "-": "subtraction", "*": "multiplication", "/": "division"}
            same = ", ".join(names[op] for op in choice.same_operations)
            following = ", ".join(names[op] for op in choice.request.constraints.allowed_operations)
            return CoachReply(
                "clarify", 
                (
                    f"For difficulty {choice.request.difficulty}, would you like to keep {same}, "
                    f"or use the next level's operators ({following})? "
                    "Reply 'same operators' (or 'yes') to keep them, or 'next level operators' (or 'no') to change. "
                    "I'll use the selected number ranges and operation count."
                    ),
                    )
        return await self._generate(session, CoachDecision("generate_problem", request=choice.request), on_rejection)

    async def _pending_choice(self, session: CoachSession, text: str, on_rejection) -> CoachReply | None:
        """Resolve simple difficulty choices locally before ordinary hint or answer actions."""
        choice = session.pending_difficulty
        if choice is None:
            return None
        normalized = " ".join(text.lower().rstrip("!?.").split())
        yes = normalized in {"yes", "yes please", "sure", "yep", "yeah"}
        no = normalized in {"no", "no thanks", "no thank you", "nope", "i don't want to specify limits", "use default limits", "default limits"}
        if normalized in {"cancel", "cancel that", "never mind", "nevermind"}:
            session.pending_difficulty = None
            return CoachReply(
                "decline", 
                "Okay. You can continue the current problem or request another one." if session.active else messages.ACKNOWLEDGEMENT,
                )
        if choice.kind in {"limits", "custom_limits"}:
            if yes:
                choice.kind = "custom_limits"
                return CoachReply(
                    "clarify", 
                    "Tell me the operand, intermediate, and final answer ranges or number of operations you'd like. Whole numbers and exact division still apply.",
                    )
            if no:
                return await self._advance_choice(session, choice, on_rejection)
        elif choice.kind == "operators":
            keep = yes or normalized in {"same", "same operators", "keep the same operators", "keep them"}
            use_preset = no or normalized in {"next level operators", "default operators", "use the defaults", "use next level operators"}
            if keep or use_preset:
                request = choice.request
                if keep:
                    request = change_operators(
                        request, 
                        self.interpreter.constraints, 
                        choice.same_operations, 
                        choice.same_required,
                        )
                return await self._generate(session, CoachDecision("generate_problem", request=request), on_rejection)
        return None

    async def _generate(self, session: CoachSession, decision: CoachDecision, on_rejection) -> CoachReply:
        """Generate a replacement before changing the current problem record."""
        request = decision.request if decision.intent == "generate_problem" else session.repeat_request
        source = "learner_repeat" if decision.intent == "repeat_problem" else "learner_request"
        if request is None:
            source = "default"
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
        if self.request_resolver is not None:
            request = self.request_resolver(session, request, source)
            if request.intent != "generate_problem":
                return CoachReply(decision.intent, route=request)
        selection = (request.diagnostics or {}).get("selection", {})
        source = selection.get("source", source)
        from coach.calculations import select_calculation
        try:
            plan = (
                self.calculation_selector(request.constraints) 
                if self.calculation_selector is not None
                else select_calculation(
                    request.constraints,
                    preferred_operations=practice_preset(request.difficulty).preferred_operations)
                    )
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
        events: tuple[LearningEvent, ...] = ()
        if session.active:
            session.run.outcome = "replaced"
            events = (ProblemEnded(session.run.problem_id, "abandoned", "replacement"),)
        session.run = ProblemRun(result)
        session.state = CoachState.AWAITING_ANSWER
        session.difficulty = getattr(result.problem, "difficulty", request.difficulty)
        session.language = request.language
        session.repeat_request = request
        session.practice_metadata = dict(selection)
        session.pending_difficulty = None
        return CoachReply(
            decision.intent, 
            result.problem.statement, 
            generated=result, 
            events=events + (ProblemStarted(
                session.run.problem_id, 
                result, 
                request, 
                source,
                selection,
                ),
            ))

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
        events: tuple[LearningEvent, ...] = (AttemptMade(
            run.problem_id, 
            decision.value, 
            expected, 
            target, 
            final, 
            correct, 
            run.hints_used,
            run.validated.analysis.steps[target].operation if target is not None else None,
            ),
            )
        if not correct:
            session.state = CoachState.OFFERING_HINT
            return CoachReply("answer", messages.OFFER_HINT, events=events)
        if final:
            run.outcome = "solved"
            session.state = CoachState.PROBLEM_COMPLETE
            if target is not None:
                run.steps_solved = target + 1
            return CoachReply(
                "answer", 
                messages.completion_reply(), 
                events=events + (ProblemEnded(
                    run.problem_id, 
                    "solved", 
                    "guided_completion" if target is not None else "correct_answer"
                    ), 
                    )
                    )
        run.steps_solved = target + 1
        run.step_index = target + 1
        run.hint_level = 0
        run.last_hint = None
        session.state = CoachState.AWAITING_ANSWER
        step = run.validated.analysis.steps[run.step_index]
        return CoachReply(
            "answer", 
            f"That's right for that step.\n\nStep {run.step_index + 1} of {len(run.validated.analysis.steps)}: "
            f"work out {step.left} {step.operation} {step.right}. What is this step's result?",
            events=events,
            )

    async def _hint(self, session: CoachSession, intent: str, *, question: str = "") -> CoachReply:
        """Deliver progressive guidance or repeat it without consuming another level."""
        if not session.active:
            return CoachReply(intent, messages.NO_PROBLEM)
        run = session.run
        if intent == "repeat_hint" and run.last_hint:
            session.state = CoachState.AWAITING_ANSWER
            return CoachReply(
                intent, 
                run.last_hint, 
                events=(HintShown(
                    run.problem_id, 
                    "repeat", 
                    run.hint_level, 
                    run.step_index, 
                    False,
                    ),
                    )
                    )
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
        return CoachReply(
            intent, 
            text, 
            events=(HintShown(
                run.problem_id, 
                "explanation" if intent == "explain" else "guidance",
                plan.level, 
                plan.step_index, 
                not repeat,
                ),
                )
                )
