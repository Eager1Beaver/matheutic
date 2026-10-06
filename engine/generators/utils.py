from __future__ import annotations

import random


def weighted_choice(
        rng: random.Random, 
        items: list[str], 
        weights: dict[str, float] | None = None,
        ) -> str:
    """Pick an item from items with optional weights mapping."""
    if not weights:
        return rng.choice(items)

    total = 0.0
    cum: list[float] = []
    for it in items:
        w = float(weights.get(it, 1.0))
        if w < 0:
            w = 0.0
        total += w
        cum.append(total)

    if total <= 0:
        return rng.choice(items)

    x = rng.random() * total
    for it, c in zip(items, cum):
        if x < c:
            return it
    return items[-1]
