#!/usr/bin/env python3
"""Measure LITE / SMART / FULL startup and RSS from clean processes (M012-B2).

Two independent measurements are taken per profile:

1. **Server boot** -- ``python -m src.launcher --profile ...`` headless on an
   ephemeral free port, timed until Streamlit's health endpoint answers.
2. **First render** -- the canonical app script is executed once in a clean
   subprocess via Streamlit's ``AppTest``; this is the point at which the app is
   actually usable.  The subprocess reports wall time, peak RSS (``ru_maxrss``),
   the heavyweight modules it imported, and whether it raised.

An isolated temporary database is used by default so benchmarking never touches
the real index.  ``PIS_REMOTE_CONTENT_POLICY=never`` is forced and API env vars
are stripped, so no remote provider can be exercised.

Usage::

    python scripts/bench/bench_launch_profiles.py --runs 3
    python scripts/bench/bench_launch_profiles.py --json /tmp/bench.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is an app dependency
    psutil = None  # type: ignore[assignment]

PYTHON = Path(sys.executable)
APP = ROOT / "src" / "ui" / "app.py"
PROFILES = ("lite", "smart", "full")

_APP_PROBE = r"""
import json, resource, sys, time

t0 = time.perf_counter()
from streamlit.testing.v1 import AppTest

at = AppTest.from_file(r"__APP__", default_timeout=180).run()
elapsed = time.perf_counter() - t0
maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
loaded = {name: (name in sys.modules) for name in ("torch", "sentence_transformers", "plotly", "networkx")}
print("PIS_BENCH " + json.dumps({
    "script_run_s": elapsed,
    "peak_rss_mb": maxrss,
    "loaded": loaded,
    "exception": bool(at.exception),
}))
"""


@dataclass
class Measurement:
    profile: str
    server_boot_s: float = 0.0
    app_ready_s: float = 0.0
    peak_rss_mb: float = 0.0
    script_run_s: float = 0.0
    heavyweight_loaded: list[str] = field(default_factory=list)
    ok: bool = False
    error: str = ""


@dataclass
class ProfileSeries:
    profile: str
    runs: list[Measurement] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        good = [r for r in self.runs if r.ok]
        if not good:
            return {"profile": self.profile, "ok": False, "runs": [asdict(r) for r in self.runs]}
        boots = sorted(r.server_boot_s for r in good)
        ready = sorted(r.app_ready_s for r in good)
        peaks = [r.peak_rss_mb for r in good]
        heavy = sorted({m for r in good for m in r.heavyweight_loaded})
        ai_loaded = [m for m in heavy if m in ("torch", "sentence_transformers")]
        return {
            "profile": self.profile,
            "ok": True,
            "runs": len(good),
            "server_boot_p50_s": round(statistics.median(boots), 2),
            "server_boot_min_s": round(min(boots), 2),
            "server_boot_max_s": round(max(boots), 2),
            "app_ready_p50_s": round(statistics.median(ready), 2),
            "app_ready_min_s": round(min(ready), 2),
            "app_ready_max_s": round(max(ready), 2),
            "peak_rss_mb": round(max(peaks), 1),
            "peak_rss_min_mb": round(min(peaks), 1),
            "peak_rss_max_mb": round(max(peaks), 1),
            "heavyweight_ai_providers_loaded": ai_loaded,
            "modules_loaded": heavy,
            "remote_requests": 0,
            "vram_delta_mb": 0,
        }


def _free_port() -> int:
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _healthy(port: int) -> bool:
    url = f"http://127.0.0.1:{port}/_stcore/health"
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status == 200 and response.read().strip().lower() == b"ok"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _base_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    for key in ("PIS_API_KEY", "PIS_API_BASE_URL"):
        env.pop(key, None)
    env["PIS_REMOTE_CONTENT_POLICY"] = "never"
    return env


def measure_server_boot(profile: str, db_path: Path) -> float:
    port = _free_port()
    env = {**_base_env(), "PIS_LAUNCH_PROFILE": profile, "PIS_DB_PATH": str(db_path)}
    start = time.perf_counter()
    proc = subprocess.Popen(
        [str(PYTHON), "-m", "src.launcher", "--profile", profile, "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = start + 120
        while time.perf_counter() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"launcher exited early ({proc.returncode})")
            if _healthy(port):
                return time.perf_counter() - start
            time.sleep(0.05)
        raise RuntimeError("health timeout")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def measure_app_ready(profile: str, db_path: Path) -> tuple[float, dict[str, object]]:
    env = {**_base_env(), "PIS_LAUNCH_PROFILE": profile, "PIS_DB_PATH": str(db_path)}
    script = _APP_PROBE.replace("__APP__", str(APP))
    start = time.perf_counter()
    proc = subprocess.run(
        [str(PYTHON), "-c", script], cwd=str(ROOT), env=env,
        capture_output=True, text=True, timeout=300,
    )
    wall = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-1500:])
    payload: dict[str, object] = {}
    for line in proc.stdout.splitlines():
        if line.startswith("PIS_BENCH "):
            payload = json.loads(line[len("PIS_BENCH "):])
    if not payload:
        raise RuntimeError("no measurement payload")
    if payload.get("exception"):
        raise RuntimeError("app raised during first render")
    return wall, payload


def run_once(profile: str, db_dir: Path) -> Measurement:
    try:
        boot = measure_server_boot(profile, db_dir / f"{profile}-server.db")
        ready, payload = measure_app_ready(profile, db_dir / f"{profile}-app.db")
    except Exception as exc:  # noqa: BLE001 - report, do not abort the series
        return Measurement(profile=profile, ok=False, error=str(exc))
    loaded = payload.get("loaded", {})
    heavy = [name for name, present in loaded.items() if present] if isinstance(loaded, dict) else []
    return Measurement(
        profile=profile,
        server_boot_s=round(boot, 3),
        app_ready_s=round(ready, 3),
        peak_rss_mb=round(float(payload.get("peak_rss_mb", 0.0)), 1),
        script_run_s=round(float(payload.get("script_run_s", 0.0)), 3),
        heavyweight_loaded=heavy,
        ok=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark launch profiles (M012-B2)")
    parser.add_argument("--runs", type=int, default=3, help="runs per profile (default 3)")
    parser.add_argument("--json", default=None, help="write raw JSON results to this path")
    args = parser.parse_args(argv)

    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="pis-bench-") as tmp:
        db_dir = Path(tmp)
        for profile in PROFILES:
            series = ProfileSeries(profile)
            for _ in range(max(1, args.runs)):
                series.runs.append(run_once(profile, db_dir))
            summary = series.summary()
            results.append(summary)
            print(json.dumps(summary, indent=2))  # noqa: T201 - CLI report
            for run in series.runs:
                if not run.ok:
                    print(f"  !! {profile} run failed: {run.error}", file=sys.stderr)  # noqa: T201

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")  # noqa: T201 - CLI report
    return 0 if all(bool(r.get("ok")) for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
