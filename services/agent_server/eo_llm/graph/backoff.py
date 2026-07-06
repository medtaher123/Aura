"""Retry backoff strategies for tool plan execution."""

from __future__ import annotations

import random
from typing import Protocol


class BackoffStrategy(Protocol):
    def compute_delay_ms(self, initial_delay: int, attempt: int) -> int: ...


class FixedBackoff:
    def compute_delay_ms(self, initial_delay: int, attempt: int) -> int:
        return max(0, initial_delay)


class ExponentialJitterBackoff:
    def compute_delay_ms(self, initial_delay: int, attempt: int) -> int:
        base_ms = max(0, initial_delay)
        exp_ms = base_ms * (2 ** max(0, attempt - 1))
        jitter = random.randint(0, max(1, exp_ms // 3))
        return exp_ms + jitter


_BACKOFF_STRATEGIES: dict[str, BackoffStrategy] = {
    "fixed": FixedBackoff(),
    "exponential_jitter": ExponentialJitterBackoff(),
}


def backoff_strategy_for(mode: str) -> BackoffStrategy | None:
    return _BACKOFF_STRATEGIES.get(mode)
