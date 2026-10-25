from __future__ import annotations

from collections.abc import Sequence

import pytest

from evident.eval.metrics import Rate, bootstrap_ci, clopper_pearson_upper


@pytest.mark.parametrize("k,n,expected", [(0, 45, 0.0644), (0, 100, 0.0295), (0, 1000, 0.00299)])
def test_clopper_pearson_zero_errors(k: int, n: int, expected: float) -> None:
    assert clopper_pearson_upper(k, n) == pytest.approx(expected, abs=5e-4)


def test_clopper_pearson_some_errors_and_all_errors() -> None:
    # Checked against the binomial definition: the largest p with P(X <= 3 | 45, p) = 0.05.
    assert clopper_pearson_upper(3, 45) == pytest.approx(0.1634, abs=5e-4)
    assert clopper_pearson_upper(45, 45) == 1.0


@pytest.mark.parametrize("k,n", [(0, 0), (-1, 10), (11, 10)])
def test_cp_rejects_empty(k: int, n: int) -> None:
    with pytest.raises(ValueError):
        clopper_pearson_upper(k, n)


def flat_mean(clusters: Sequence[list[float]]) -> float:
    values = [v for c in clusters for v in c]
    return sum(values) / len(values)


def test_bootstrap_deterministic_and_brackets_mean() -> None:
    # Five "documents", each a cluster of per-field scores, resampled as whole documents.
    clusters = [[1.0, 1.0, 0.0], [1.0, 1.0], [0.0, 1.0, 1.0, 1.0], [1.0], [0.0, 0.0, 1.0]]
    first = bootstrap_ci(clusters, flat_mean, n_resamples=2000, seed=7)
    assert first == bootstrap_ci(clusters, flat_mean, n_resamples=2000, seed=7)
    lo, hi = first
    assert lo <= flat_mean(clusters) <= hi and lo < hi
    assert lo >= 0.0 and hi <= 1.0


def test_bootstrap_resamples_whole_clusters() -> None:
    # One cluster can only be resampled as itself, so the interval collapses to its mean.
    assert bootstrap_ci([[1.0, 0.0, 0.0, 1.0]], flat_mean, n_resamples=200) == (0.5, 0.5)


def test_bootstrap_rejects_no_clusters() -> None:
    with pytest.raises(ValueError):
        bootstrap_ci([], flat_mean)


def test_rate_format() -> None:
    assert str(Rate(0, 45)) == "0/45 (0.0%, 95% upper 6.4%)"
    rate = Rate(3, 40)
    assert rate.value == pytest.approx(0.075)
    assert rate.upper == pytest.approx(clopper_pearson_upper(3, 40))
    assert str(rate).startswith("3/40 (7.5%, 95% upper ")
