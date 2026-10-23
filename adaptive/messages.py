"""Explicit practice proposals and factual descriptions of their targets."""

NAMES = {
    "+": "addition", 
    "-": "subtraction", 
    "*": "multiplication", 
    "/": "division",
    }
# TODO: localization concern
REASONS = {
    "independent_progress": "You've been solving these problems independently on your first try.",
    "foundation_progress": "You've been doing well with this one-step addition practice.",
    "recent_support": "These recent problems have needed several retries or a solution reveal.",
    "operator_support": "Several recent calculations with this operator have needed extra support.",
    "declared_support": "You mentioned wanting support with this operator.",
    }


def describe(request) -> str:
    c = request.constraints
    operators = ", ".join(NAMES[op] for op in c.allowed_operations)
    count = str(c.min_operations) if c.min_operations == c.max_operations else f"{c.min_operations}-{c.max_operations}"
    result = (
        f"{c.min_final_value or 0}..{c.max_final_value}" 
        if c.max_final_value is not None 
        else f"{c.min_final_value or 0} or higher")
    intermediate = (
        f"{c.min_intermediate_value or 0}..{c.max_intermediate_value}"
        if c.max_intermediate_value is not None 
        else f"{c.min_intermediate_value or 0} or higher"
        )
    required = ", ".join(NAMES[op] for op in c.required_operations)
    return (
        f"level {request.difficulty}: {operators}" + (f" (including {required})" if required else "") +
        f", {count} operation(s), operands {c.min_operand}..{c.max_operand}, "
        f"intermediate results {intermediate}, and answers {result}"
        )


def offer(proposal) -> str:
    return (f"{REASONS[proposal.reason]} Would you like to try {describe(proposal.target)}? "
            "Reply 'yes' to try it or 'no' to keep your current settings.")


KEEP_SETTINGS = "Okay, we'll keep your current settings. You can ask for another problem whenever you're ready."
