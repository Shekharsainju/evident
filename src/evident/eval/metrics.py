"""Measurement rules (design: Evaluation harness; invariants section 5).

Proportions get a one-sided 95% Clopper-Pearson upper bound. Scores get a bootstrap interval
that resamples whole clusters (documents or profiles), because fields from one document are
not independent.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.stats import beta


def clopper_pearson_upper(k: int, n: int, confidence: float = 0.95) -> float:
    """One-sided upper bound on the true rate after k events in n trials."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n and n > 0, got k={k}, n={n}")
    if k == n:
        return 1.0
    return float(beta.ppf(confidence, k + 1, n - k))


def bootstrap_ci[C](
    clusters: Sequence[C],
    statistic: Callable[[Sequence[C]], float],
    n_resamples: int = 10_000,
    seed: int = 0,
    level: float = 0.95,
) -> tuple[float, float]:
    """Percentile interval for `statistic`, resampling whole clusters with replacement."""
    if not clusters:
        raise ValueError("bootstrap needs at least one cluster")
    rng = np.random.default_rng(seed)
    n = len(clusters)
    values = [statistic([clusters[i] for i in rng.integers(0, n, size=n)])
              for _ in range(n_resamples)]
    tail = (1.0 - level) / 2 * 100
    lo, hi = np.percentile(values, [tail, 100 - tail])
    return float(lo), float(hi)


@dataclass(frozen=True)
class Rate:
    """A proportion reported as numerator/denominator with its upper bound."""

    k: int
    n: int

    def __post_init__(self) -> None:
        clopper_pearson_upper(self.k, self.n)  # rejects n == 0 and k outside 0..n

    @property
    def value(self) -> float:
        return self.k / self.n

    @property
    def upper(self) -> float:
        return clopper_pearson_upper(self.k, self.n)

    def __str__(self) -> str:
        return f"{self.k}/{self.n} ({self.value:.1%}, 95% upper {self.upper:.1%})"
