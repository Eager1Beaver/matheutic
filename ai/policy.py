"""Application policy for natural-number arithmetic practice."""
from dataclasses import replace

from core.constraints import ProblemConstraints


def natural_number_policy(constraints: ProblemConstraints | None = None) -> ProblemConstraints:
    """Require exact integer division and non-negative final and intermediate values."""
    if constraints is None:
        constraints = ProblemConstraints()
    if not isinstance(constraints, ProblemConstraints):
        raise TypeError("constraints must be ProblemConstraints")
    if (constraints.require_integer_division and constraints.non_negative
            and constraints.non_negative_intermediate):
        return constraints
    return replace(
        constraints, 
        require_integer_division=True, 
        non_negative=True,
        non_negative_intermediate=True,
        )
