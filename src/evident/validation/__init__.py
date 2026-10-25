"""Claim validation: Layer 1 deterministic checks, the Layer 2 judge and the outcome table."""

from evident.validation.judge import JUDGE_THRESHOLD, limitations, run_judge
from evident.validation.layer1.config import Layer1Context, load_aliases, load_lexicons
from evident.validation.layer1.run import run_layer1
from evident.validation.outcome import decide, validate_claim

__all__ = [
    "JUDGE_THRESHOLD",
    "Layer1Context",
    "decide",
    "limitations",
    "load_aliases",
    "load_lexicons",
    "run_judge",
    "run_layer1",
    "validate_claim",
]
