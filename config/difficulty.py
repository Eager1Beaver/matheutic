"""Configurable arithmetic practice presets for difficulty levels one through five."""
from dataclasses import dataclass


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


DEFAULT_DIFFICULTY = 1
DIFFICULTY_PRESETS = {
    1: DifficultyPreset(("+", "-"), 0, 50, 0, 50, 0, 50, 1, 2),
    2: DifficultyPreset(("+", "-"), 0, 99, 0, 99, 0, 99, 1, 2),
    3: DifficultyPreset(("+", "-", "*"), 0, 99, 0, 99, 0, 200, 2, 3),
    4: DifficultyPreset(("+", "-", "*", "/"), 0, 250, 0, 250, 0, 250, 3, 3),
    5: DifficultyPreset(("+", "-", "*", "/"), 0, 1000, 0, 1000, 0, 1000, 4, 4),
}


def difficulty_preset(level: int) -> DifficultyPreset:
    """Return the configured preset for a supported integer difficulty."""
    if type(level) is not int or level not in DIFFICULTY_PRESETS:
        raise ValueError("Difficulty must be an integer from 1 to 5")
    return DIFFICULTY_PRESETS[level]
