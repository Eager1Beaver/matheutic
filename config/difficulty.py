"""Configurable arithmetic presets and magnitude increases for continued practice."""
from dataclasses import dataclass, replace

from core.expression import MAX_OPERAND_VALUE


@dataclass(frozen=True)
class DifficultyPreset:
    allowed_operations: tuple[str, ...]
    min_operand: int
    max_operand: int
    min_intermediate_value: int
    max_intermediate_value: int
    min_final_value: int
    max_final_value: int
    min_operations: int
    max_operations: int
    preferred_operations: int


DEFAULT_DIFFICULTY = 1
DIFFICULTY_PRESETS = {
    1: DifficultyPreset(("+", "-"), 0, 50, 0, 50, 0, 50, 1, 2, 1),
    2: DifficultyPreset(("+", "-"), 0, 99, 0, 99, 0, 99, 1, 2, 2),
    3: DifficultyPreset(("+", "-", "*"), 0, 99, 0, 99, 0, 200, 2, 3, 3),
    4: DifficultyPreset(("+", "-", "*", "/"), 0, 250, 0, 250, 0, 250, 3, 3, 3),
    5: DifficultyPreset(("+", "-", "*", "/"), 0, 1000, 0, 1000, 0, 1000, 4, 4, 4),
    }
PROGRESSION_INCREMENT = 1000
MAX_PROGRESSIVE_DIFFICULTY = 5 + (MAX_OPERAND_VALUE - DIFFICULTY_PRESETS[5].max_operand) // PROGRESSION_INCREMENT


def difficulty_preset(level: int) -> DifficultyPreset:
    """Return the configured preset for a supported integer difficulty."""
    if type(level) is not int or level not in DIFFICULTY_PRESETS:
        raise ValueError("Difficulty must be an integer from 1 to 5")
    return DIFFICULTY_PRESETS[level]


def practice_preset(level: int) -> DifficultyPreset:
    """Return a standard preset or a bounded continuation above level five."""
    if type(level) is not int or not 1 <= level <= MAX_PROGRESSIVE_DIFFICULTY:
        raise ValueError("Difficulty exceeds the supported practice range")
    if level <= 5:
        return difficulty_preset(level)
    base = difficulty_preset(5)
    maximum = base.max_operand + (level - 5) * PROGRESSION_INCREMENT
    return replace(
        base, 
        max_operand=maximum, 
        max_intermediate_value=maximum, 
        max_final_value=maximum,
        )
