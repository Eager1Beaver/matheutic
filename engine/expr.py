from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Brackets:
    start: int  # index into numbers
    end: int    # index into numbers (inclusive)


@dataclass(frozen=True)
class Expression:
    numbers: List[int]
    ops: List[str]  # length = len(numbers) - 1
    brackets: Optional[Brackets] = None

    def __post_init__(self):
        if len(self.numbers) < 2:
            raise ValueError('Expression must have at least 2 numbers')
        if len(self.ops) != len(self.numbers) - 1:
            raise ValueError('ops length must be len(numbers)-1')
