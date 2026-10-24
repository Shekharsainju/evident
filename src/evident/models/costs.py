"""Cost estimates at paid list prices; the free tier's actual cost is zero."""

from __future__ import annotations

from evident.settings import Price


def estimate_cost(price: Price | None, input_tokens: int, output_tokens: int) -> float:
    if price is None:
        return 0.0
    return (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1e6
