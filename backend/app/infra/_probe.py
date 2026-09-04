"""Small helpers shared by the infrastructure reachability probes."""

from __future__ import annotations

import time


class Stopwatch:
    __slots__ = ("_start",)

    def __init__(self) -> None:
        self._start = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self._start) * 1000, 1)


def describe_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".strip()
    return text[:200]
