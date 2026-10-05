from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Optional

OPERATORS = ('+', '-', '*', '/')


@dataclass(frozen=True)
class Brackets:
    start: int  # index into numbers
    end: int    # index into numbers (inclusive)

    def __post_init__(self):
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end:
            raise ValueError('brackets require integer indices with 0 <= start < end')


@dataclass(frozen=True)
class Expression:
    numbers: Sequence[int]
    ops: Sequence[str]  # length = len(numbers) - 1
    brackets: Optional[Brackets] = None

    def __post_init__(self):
        if not isinstance(self.numbers, (list, tuple)) or not isinstance(self.ops, (list, tuple)):
            raise ValueError('numbers and ops must be arrays')
        if len(self.numbers) < 2:
            raise ValueError('Expression must have at least 2 numbers')
        if len(self.ops) != len(self.numbers) - 1:
            raise ValueError('ops length must be len(numbers)-1')
        if not all(type(n) is int for n in self.numbers):
            raise ValueError('operands must be integers (not booleans)')
        if not all(op in OPERATORS for op in self.ops):
            raise ValueError('operators must be one of + - * /')
        if self.brackets is not None:
            if not isinstance(self.brackets, Brackets) or self.brackets.end >= len(self.numbers):
                raise ValueError('invalid brackets span')
        object.__setattr__(self, 'numbers', tuple(self.numbers))
        object.__setattr__(self, 'ops', tuple(self.ops))
