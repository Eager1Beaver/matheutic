"""Bounded analysis of integer-literal arithmetic using exact rational values."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from fractions import Fraction

MAX_EXPRESSION_LENGTH = 200
MAX_OPERAND_VALUE = 10**9
MAX_OPERATION_COUNT = 31
MAX_ARITHMETIC_BITS = 512
_MAX_AST_NODES = 128
_MAX_AST_DEPTH = 32


class ExpressionError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_expression") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ArithmeticStep:
    left: Fraction
    operation: str
    right: Fraction
    result: Fraction


@dataclass(frozen=True)
class ExpressionAnalysis:
    value: Fraction
    operands: tuple[int, ...]
    operations: tuple[str, ...]
    intermediate_values: tuple[Fraction, ...]
    steps: tuple[ArithmeticStep, ...] = ()


_OPERATOR_SYMBOLS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}


def expression_structure(expression: str, *, commutative: bool = False) -> tuple:
    """Return a checked arithmetic tree, optionally ignoring commutative order."""
    analyze_expression(expression)

    def structure(node: ast.AST) -> tuple:
        if isinstance(node, ast.Constant):
            return ("number", node.value)
        left, right = structure(node.left), structure(node.right)
        operator = _OPERATOR_SYMBOLS[type(node.op)]
        if commutative and operator in {"+", "*"}:
            left, right = sorted((left, right))
        return (operator, left, right)

    return structure(ast.parse(expression.strip(), mode="eval").body)


def analyze_expression(expression: str) -> ExpressionAnalysis:
    """Derive values, operands, operators, and ordered steps from arithmetic text."""
    if not isinstance(expression, str):
        raise ExpressionError("Expression must be a string.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError("Expression is too long.", code="expression_too_long")
    expression = expression.strip()
    if not expression:
        raise ExpressionError("Expression must not be empty.")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as error:
        raise ExpressionError("Expression is not valid arithmetic.") from error

    nodes = list(ast.walk(tree))
    if len(nodes) > _MAX_AST_NODES:
        raise ExpressionError("Expression has too many elements.", code="expression_too_complex")
    if sum(isinstance(node, ast.BinOp) for node in nodes) > MAX_OPERATION_COUNT:
        raise ExpressionError("Expression has too many operations.", code="expression_too_complex")

    operands: list[int] = []
    operations: list[str] = []
    steps: list[ArithmeticStep] = []

    def evaluate(node: ast.AST, depth: int = 1) -> Fraction:
        if depth > _MAX_AST_DEPTH:
            raise ExpressionError("Expression is too deeply nested.", code="expression_too_complex")
        
        if isinstance(node, ast.Constant):
            if type(node.value) is not int:
                raise ExpressionError("Only integer operands are allowed.", code="invalid_operand")
            literal = ast.get_source_segment(expression, node)
            if literal is None or re.fullmatch(r"[0-9]+", literal) is None:
                raise ExpressionError("Only decimal integer literals are allowed.", code="invalid_operand")
            if not 0 <= node.value <= MAX_OPERAND_VALUE:
                raise ExpressionError("Operand exceeds the arithmetic limit.", code="operand_too_large")
            operands.append(node.value)
            return Fraction(node.value)
        
        if not isinstance(node, ast.BinOp):
            raise ExpressionError(
                f"Unsupported expression element: {type(node).__name__}.", code="unsupported_syntax"
                )
        
        operator_type = type(node.op)
        if operator_type not in _OPERATOR_SYMBOLS:
            raise ExpressionError(
                f"Unsupported operator: {operator_type.__name__}.", code="unsupported_operator"
                )
        
        left, right = evaluate(node.left, depth + 1), evaluate(node.right, depth + 1)
        if operator_type is ast.Add:
            result = left + right
        elif operator_type is ast.Sub:
            result = left - right
        elif operator_type is ast.Mult:
            result = left * right
        else:
            if right == 0:
                raise ExpressionError("Division by zero.", code="division_by_zero")
            result = left / right
        
        if (abs(result.numerator).bit_length() > MAX_ARITHMETIC_BITS
                or result.denominator.bit_length() > MAX_ARITHMETIC_BITS):
            raise ExpressionError("Intermediate value exceeds the arithmetic limit.", code="value_too_large")
        
        symbol = _OPERATOR_SYMBOLS[operator_type]
        operations.append(symbol)
        steps.append(ArithmeticStep(left, symbol, right, result))
        return result

    value = evaluate(tree.body)
    # AST evaluation ignores comments and line continuations; the arithmetic
    # language admits only decimal digits, its operators, brackets, and spaces.
    if re.fullmatch(r"[0-9+*/()\s-]+", expression, flags=re.ASCII) is None:
        raise ExpressionError("Expression contains non-arithmetic text.", code="unsupported_syntax")
    return ExpressionAnalysis(
        value, tuple(operands), tuple(operations), tuple(step.result for step in steps), tuple(steps)
        )
