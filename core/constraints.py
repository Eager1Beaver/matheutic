"""Application-owned constraints for arithmetic problem validation."""
from dataclasses import dataclass

from core.expression import MAX_ARITHMETIC_BITS, MAX_OPERAND_VALUE, MAX_OPERATION_COUNT

SUPPORTED_OPERATIONS = ("+", "-", "*", "/")


@dataclass(frozen=True)
class ProblemConstraints:
    allowed_operations: tuple[str, ...] = SUPPORTED_OPERATIONS
    required_operations: tuple[str, ...] = ()
    min_operand: int = 0
    max_operand: int = MAX_OPERAND_VALUE
    min_operations: int = 1
    max_operations: int = 15
    require_integer_division: bool = True
    non_negative: bool = False
    non_negative_intermediate: bool | None = None
    max_intermediate_value: int | None = None
    max_final_value: int | None = None

    def __post_init__(self) -> None:
        for field in ("allowed_operations", "required_operations"):
            value = getattr(self, field)
            if not isinstance(value, (list, tuple)) or not all(op in SUPPORTED_OPERATIONS for op in value):
                raise ValueError(f"{field} must contain supported arithmetic operators")
            if len(set(value)) != len(value):
                raise ValueError(f"{field} must not contain duplicates")
            object.__setattr__(self, field, tuple(value))
        if not self.allowed_operations or not set(self.required_operations) <= set(self.allowed_operations):
            raise ValueError("Required operations must be allowed")
        if not all(type(value) is int and 0 <= value <= MAX_OPERAND_VALUE
                   for value in (self.min_operand, self.max_operand)) or self.min_operand > self.max_operand:
            raise ValueError("Operand bounds must be ordered non-negative integers within the arithmetic limit")
        if not all(type(value) is int and 1 <= value <= MAX_OPERATION_COUNT
                   for value in (self.min_operations, self.max_operations)) or self.min_operations > self.max_operations:
            raise ValueError("Operation counts must be ordered positive integers within the arithmetic limit")
        if len(self.required_operations) > self.max_operations:
            raise ValueError("Required operations exceed the maximum operation count")
        for field in ("require_integer_division", "non_negative"):
            if type(getattr(self, field)) is not bool:
                raise ValueError(f"{field} must be a boolean")
        if self.non_negative_intermediate is None:
            object.__setattr__(self, "non_negative_intermediate", self.non_negative)
        elif type(self.non_negative_intermediate) is not bool:
            raise ValueError("non_negative_intermediate must be a boolean")
        for field in ("max_intermediate_value", "max_final_value"):
            value = getattr(self, field)
            if value is not None and (type(value) is not int or value < 0
                                      or value.bit_length() > MAX_ARITHMETIC_BITS):
                raise ValueError(f"{field} must be a non-negative integer within the arithmetic limit")
