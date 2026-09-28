"""Progress/ETA presentation contract for the canonical Scanner (SCAN-UI-01B).

The progress bar is display-only.  ``ScanService`` remains the sole owner of
the COMPLETED / CANCELLED / FAILED lifecycle, so these tests pin:

* the running bar is capped at 99 % and never reaches 100 % before COMPLETED;
* only a real COMPLETED produces 100 %;
* CANCELLED / FAILED freeze the bar and never show an ETA;
* an ETA is surfaced only when the observed rate is stable.
"""
from __future__ import annotations

from src.ui.scan_progress import (
    MAX_RUNNING_FRACTION,
    RateTracker,
    format_duration,
    progress_view,
    running_fraction,
)


def test_running_progress_is_capped_at_99_percent() -> None:
    view = progress_view("running", seen=1000, estimated_total=1000)
    assert view.fraction == MAX_RUNNING_FRACTION == 0.99
    assert view.percent_label == "99 %"
    assert view.fraction < 1.0


def test_running_progress_capped_even_when_seen_exceeds_estimate() -> None:
    # A bounded (lower-bound) estimate can be smaller than the real count.
    view = progress_view("running", seen=5000, estimated_total=1000)
    assert view.fraction == 0.99


def test_only_completed_reaches_100_percent() -> None:
    running = progress_view("running", seen=1000, estimated_total=1000)
    assert running.fraction == 0.99

    completed = progress_view("completed", seen=1000, estimated_total=1000)
    assert completed.fraction == 1.0
    assert completed.percent_label == "100 %"


def test_completed_is_100_percent_even_without_estimate() -> None:
    view = progress_view("completed", seen=42, estimated_total=None)
    assert view.fraction == 1.0
    assert view.percent_label == "100 %"


def test_cancelled_and_failed_freeze_the_bar() -> None:
    for status in ("cancelled", "failed"):
        view = progress_view(status, seen=500, estimated_total=1000)
        assert view.fraction == 0.5
        assert view.fraction < 1.0
        assert view.eta_seconds is None
        assert view.eta_stable is False


def test_indeterminate_when_estimate_unavailable() -> None:
    view = progress_view("running", seen=10, estimated_total=None)
    assert view.fraction is None
    assert view.estimated is False
    assert view.percent_label is None
    assert running_fraction(10, 0) is None
    assert running_fraction(10, None) is None


def test_no_eta_when_no_samples() -> None:
    tracker = RateTracker(window=8, min_samples=4, min_elapsed_s=3.0)
    assert tracker.is_stable() is False
    assert tracker.rate() is None
    assert tracker.eta_seconds(1000) is None


def test_no_eta_when_rate_is_unstable() -> None:
    tracker = RateTracker(window=8, min_samples=4, min_elapsed_s=3.0)
    for elapsed, seen in [(1.0, 10), (2.0, 500), (3.0, 520), (4.0, 4000)]:
        tracker.add(elapsed, seen)
    assert tracker.is_stable() is False
    assert tracker.eta_seconds(1000) is None
    view = progress_view(
        "running",
        seen=4000,
        estimated_total=10000,
        eta_seconds=1.0,
        eta_stable=False,
    )
    assert view.eta_seconds is None


def test_eta_available_when_rate_is_stable() -> None:
    tracker = RateTracker(window=8, min_samples=4, min_elapsed_s=3.0, max_cv=0.5)
    for i in range(1, 7):
        tracker.add(float(i), i * 100)  # a constant 100 files/s
    assert tracker.is_stable() is True
    eta = tracker.eta_seconds(1000)
    assert eta is not None
    assert abs(eta - 10.0) < 1e-6


def test_rate_tracker_resets_when_counter_decreases() -> None:
    tracker = RateTracker()
    tracker.add(1.0, 100)
    tracker.add(2.0, 200)
    assert tracker.samples == 2
    tracker.add(3.0, 5)  # a new root restarts the counters
    assert tracker.samples == 1


def test_format_duration() -> None:
    assert format_duration(0) == "00:00:00"
    assert format_duration(63 * 60 + 12) == "01:03:12"
    assert format_duration(None) == "—"
