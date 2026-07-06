"""Unit tests for retry backoff strategies."""

from __future__ import annotations

from eo_llm.graph.backoff import (
    ExponentialJitterBackoff,
    FixedBackoff,
    backoff_strategy_for,
)


def test_fixed_backoff_returns_initial_delay() -> None:
    strategy = FixedBackoff()
    assert strategy.compute_delay_ms(300, 1) == 300
    assert strategy.compute_delay_ms(300, 3) == 300


def test_exponential_jitter_backoff_grows_with_attempt() -> None:
    strategy = ExponentialJitterBackoff()
    first = strategy.compute_delay_ms(100, 1)
    second = strategy.compute_delay_ms(100, 2)
    third = strategy.compute_delay_ms(100, 3)

    assert 100 <= first <= 133
    assert 200 <= second <= 266
    assert 400 <= third <= 533


def test_backoff_strategy_for_known_modes() -> None:
    assert isinstance(backoff_strategy_for("fixed"), FixedBackoff)
    assert isinstance(backoff_strategy_for("exponential_jitter"), ExponentialJitterBackoff)
    assert backoff_strategy_for("none") is None
