"""Deterministic arithmetic exercise generation."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import callable

from config.schema import (
    MAX_ATTEMPTS,
    MAX_EXERCISES,
    MAX_GENERATION_BUDGET,
    ConfigError,
    validate_generator_config,
    )
from engine.eval import Step, evaluate_with_steps
from engine.expr import Expression
from engine.generators.mixed import generate_mixed
from engine.generators.simple import generate_single_op
from engine.validate import validate_expression


class GenerationError(RuntimeError):
    def __init__(self, message: str, *, reason: str, attempts: int):
        super().__init__(message)
        self.reason = reason
        self.attempts = attempts


@dataclass(frozen=True)
class Exercise:
    expression: Expression
    answer: int
    steps: tuple[Step, ...]


def generate_exercise(
        rng: random.Random, 
        gen_cfg: dict, 
        *, 
        max_attempts: int = 2000,
        accept: callable[[Exercise], bool] | None = None,
        ) -> Exercise:
    """Generate one verified exercise using an explicitly owned random stream.

    An optional acceptance filter supports adapter-specific constraints without
    making the engine depend on those adapters.
    """
    validate_generator_config(gen_cfg)
    if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise ConfigError(f'max_attempts must be an integer in [1, {MAX_ATTEMPTS}]')
    generator = generate_single_op if gen_cfg['type'] == 'single_op' else generate_mixed
    reason = 'unknown'
    for _ in range(max_attempts):
        expr = generator(rng, gen_cfg)
        valid, reason, answer = validate_expression(expr, gen_cfg)
        if not valid:
            continue
        _, steps = evaluate_with_steps(expr)
        exercise = Exercise(expr, answer, tuple(steps))
        if accept is not None and not accept(exercise):
            reason = 'adapter_rejected'
            continue
        return exercise
    raise GenerationError(
        f'Failed to generate an exercise after {max_attempts} attempts: {reason}',
        reason=reason, attempts=max_attempts,
        )


def generate_exercises(
        gen_cfg: dict, 
        count: int, 
        *, 
        seed: int | None = None, 
        max_attempts: int = 2000,
        ) -> tuple[Exercise, ...]:
    """Generate an exact count, independent of worksheet rows, fonts, or columns."""
    validate_generator_config(gen_cfg)
    if type(count) is not int or not 1 <= count <= MAX_EXERCISES:
        raise ConfigError(f'count must be an integer in [1, {MAX_EXERCISES}]')
    if seed is not None and type(seed) is not int:
        raise ConfigError('seed must be an integer or null')
    if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise ConfigError(f'max_attempts must be an integer in [1, {MAX_ATTEMPTS}]')
    if count * max_attempts > MAX_GENERATION_BUDGET:
        raise ConfigError(f'generation budget must be <= {MAX_GENERATION_BUDGET}')
    rng = random.Random(seed)
    return tuple(generate_exercise(rng, gen_cfg, max_attempts=max_attempts) for _ in range(count))
