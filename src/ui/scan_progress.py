"""Estimated progress + ETA helpers for the canonical Scanner (display only).

These helpers never decide the lifecycle.  ``ScanService`` is still the sole
owner of COMPLETED / CANCELLED / FAILED; this module only turns real counters
plus an optional bounded estimate into presentation values:

* the running bar is capped at 99 % and only reaches 100 % for a real COMPLETED;
* an ETA is returned only when the observed rate is stable enough;
* an unreadable/unbounded estimate yields an indeterminate view instead of a
  fabricated percentage.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

#: Never show 100 % while the service is still running.
MAX_RUNNING_FRACTION = 0.99


@dataclass(frozen=True)
class ProgressView:
    """Display-only progress state derived from real counters."""

    fraction: float | None
    estimated: bool
    percent_label: str | None
    eta_seconds: float | None
    eta_stable: bool


def _normalize_status(status: str | None) -> str:
    return (status or "").strip().lower()


def running_fraction(seen: int, estimated_total: int | None) -> float | None:
    """Return ``seen / estimated_total`` capped at 99 %, or None if unknown."""
    if not estimated_total or estimated_total <= 0:
        return None
    seen = max(0, int(seen))
    return min(seen / float(estimated_total), MAX_RUNNING_FRACTION)


def _percent_label(fraction: float) -> str:
    return f"{int(round(fraction * 100))} %"


def progress_view(
    status: str | None,
    seen: int,
    estimated_total: int | None,
    *,
    eta_seconds: float | None = None,
    eta_stable: bool = False,
) -> ProgressView:
    """Build the display view for *status* and the real counters.

    100 % is returned for COMPLETED only.  CANCELLED/FAILED freeze the bar at
    the last estimated fraction (capped at 99 %) and never advance it.
    """
    normalized = _normalize_status(status)
    seen = max(0, int(seen))

    if normalized == "completed":
        return ProgressView(
            fraction=1.0,
            estimated=bool(estimated_total and estimated_total > 0),
            percent_label="100 %",
            eta_seconds=0.0,
            eta_stable=True,
        )

    fraction = running_fraction(seen, estimated_total)
    if fraction is None:
        return ProgressView(None, False, None, None, False)

    show_eta = (
        normalized == "running"
        and eta_stable
        and eta_seconds is not None
        and eta_seconds >= 0
    )
    return ProgressView(
        fraction=fraction,
        estimated=True,
        percent_label=_percent_label(fraction),
        eta_seconds=eta_seconds if show_eta else None,
        eta_stable=bool(show_eta),
    )


class RateTracker:
    """Rolling file-rate samples used to decide whether an ETA is trustworthy."""

    def __init__(
        self,
        *,
        window: int = 8,
        min_samples: int = 4,
        min_elapsed_s: float = 3.0,
        max_cv: float = 0.35,
    ) -> None:
        self.window = max(2, int(window))
        self.min_samples = max(2, int(min_samples))
        self.min_elapsed_s = float(min_elapsed_s)
        self.max_cv = float(max_cv)
        self._samples: deque[tuple[float, int]] = deque(maxlen=self.window)

    def reset(self) -> None:
        self._samples.clear()

    def add(self, elapsed_s: float | None, seen: int) -> None:
        """Record a sample. A decreasing counter (new root) resets the tracker."""
        if elapsed_s is None:
            return
        elapsed = float(elapsed_s)
        if elapsed <= 0:
            return
        seen = max(0, int(seen))
        if self._samples and seen < self._samples[-1][1]:
            self.reset()
        self._samples.append((elapsed, seen))

    @property
    def samples(self) -> int:
        return len(self._samples)

    def _instant_rates(self) -> list[float]:
        samples = list(self._samples)
        rates: list[float] = []
        for (t0, s0), (t1, s1) in zip(samples, samples[1:], strict=False):
            dt = t1 - t0
            ds = s1 - s0
            if dt > 0 and ds > 0:
                rates.append(ds / dt)
        return rates

    def rate(self) -> float | None:
        """Return a robust (median) rate in files/second, or None."""
        rates = sorted(self._instant_rates())
        if not rates:
            return None
        middle = len(rates) // 2
        if len(rates) % 2:
            return rates[middle]
        return (rates[middle - 1] + rates[middle]) / 2.0

    def is_stable(self) -> bool:
        """Whether enough low-variance samples exist to trust an ETA."""
        samples = list(self._samples)
        if len(samples) < self.min_samples:
            return False
        if samples[-1][0] - samples[0][0] < self.min_elapsed_s:
            return False
        rates = self._instant_rates()
        if len(rates) < self.min_samples - 1:
            return False
        mean = sum(rates) / len(rates)
        if mean <= 0:
            return False
        variance = sum((rate - mean) ** 2 for rate in rates) / len(rates)
        coefficient_of_variation = (variance ** 0.5) / mean
        return bool(coefficient_of_variation <= self.max_cv)

    def eta_seconds(self, remaining_files: int) -> float | None:
        """Return a stable ETA, or None when no trustworthy estimate exists."""
        remaining_files = int(remaining_files)
        if remaining_files <= 0:
            return 0.0
        if not self.is_stable():
            return None
        rate = self.rate()
        if not rate or rate <= 0:
            return None
        return remaining_files / rate

    def view(
        self,
        status: str | None,
        seen: int,
        estimated_total: int | None,
    ) -> ProgressView:
        """Build the display view from the already-recorded samples."""
        normalized = _normalize_status(status)
        eta: float | None = None
        stable = False
        if normalized == "running" and estimated_total and estimated_total > 0:
            remaining = max(0, int(estimated_total) - int(seen))
            stable = self.is_stable()
            if stable:
                eta = self.eta_seconds(remaining)
                stable = eta is not None
        return progress_view(
            normalized,
            seen,
            estimated_total,
            eta_seconds=eta,
            eta_stable=stable,
        )


def format_duration(seconds: float | None) -> str:
    """Format a duration as ``HH:MM:SS`` (``—`` when unknown)."""
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
