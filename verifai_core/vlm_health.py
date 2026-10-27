"""In-process Gemini outage circuit breaker for a single local Uvicorn worker.

After repeated transient server failures, temporarily skip VLM inference for
subsequent jobs. OCR/ASR and review continue; VLM coverage is reported as error.
This never claims the external Gemini service has recovered.
"""
from __future__ import annotations

import threading
import time

_TRANSIENT = ('429', '500', '502', '503', '504',
              'UNAVAILABLE', 'DEADLINE_EXCEEDED', 'RESOURCE_EXHAUSTED')


def is_transient_gemini_error(message: str) -> bool:
    value = str(message or '').upper()
    return any(token in value for token in _TRANSIENT)


class GeminiOutageCircuit:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures = 0
        self._open_until = 0.0

    def reset(self) -> None:
        with self._lock:
            self._failures = 0
            self._open_until = 0.0

    def remaining_seconds(self, now: float | None = None) -> float:
        current = time.monotonic() if now is None else now
        with self._lock:
            return max(0.0, self._open_until - current)

    def allow(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            if current < self._open_until:
                return False
            if self._open_until:
                self._open_until = 0.0
                self._failures = 0
            return True

    def success(self) -> None:
        self.reset()

    def failure(self, message: str, *, threshold: int = 2,
                cooldown_seconds: int = 180, now: float | None = None) -> bool:
        """Return True only if this failure opens the circuit."""
        if not is_transient_gemini_error(message):
            return False
        current = time.monotonic() if now is None else now
        with self._lock:
            if current < self._open_until:
                return True
            self._failures += 1
            if self._failures >= max(1, threshold):
                self._open_until = current + max(1, cooldown_seconds)
                self._failures = 0
                return True
            return False


GEMINI_OUTAGE_CIRCUIT = GeminiOutageCircuit()
