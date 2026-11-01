#!/usr/bin/env python3
"""Budgeted quality gate for ruff + mypy.

The project carries inherited static debt (legacy UI/scanner modules). Rewriting
thousands of annotations at once is riskier than shipping the behaviour fixes, so
the gate uses a **reviewed, decreasing budget** instead of an all-or-nothing
failure:

* the repository-wide error count may never exceed the checked-in baseline;
* a file may never exceed its own baseline count;
* a *new* Python file must have zero errors;
* ``--changed BASE`` additionally forbids any regression in files changed since
  ``BASE`` (use this in pull requests).

The baseline is updated deliberately with ``--update`` and must be reviewed like
any other change. ``--update`` refuses to increase the total unless
``--allow-increase`` is passed, which keeps the ratchet honest.

Usage::

    python scripts/quality_gate.py                 # total + per-file budget
    python scripts/quality_gate.py --changed origin/main
    python scripts/quality_gate.py --update        # after fixing debt
    python scripts/quality_gate.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = ROOT / ".quality"
RUFF_BASELINE = BASELINE_DIR / "ruff-baseline.json"
MYPY_BASELINE = BASELINE_DIR / "mypy-baseline.json"
SKIP_PARTS = {".venv", ".git", "__pycache__", "build", "dist", ".mypy_cache", ".ruff_cache"}

_MYPY_RE = re.compile(r"^(?P<path>[^:]+):\d+: (?P<level>error|warning): (?P<msg>.*)$")


@dataclass
class ToolReport:
    name: str
    total: int
    files: dict[str, int]
    raw_tail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"total": self.total, "files": dict(sorted(self.files.items()))}


def _run(command: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout, proc.stderr


def collect_ruff() -> ToolReport:
    code, out, err = _run([
        sys.executable, "-m", "ruff", "check", "src", "scripts", "tests",
        "--output-format", "json",
    ])
    if code not in (0, 1):
        raise SystemExit(f"ruff failed to run (exit {code}): {err.strip()}")
    try:
        violations = json.loads(out or "[]")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"could not parse ruff JSON output: {exc}") from exc
    counts: dict[str, int] = {}
    for item in violations:
        filename = Path(item.get("filename", "")).resolve()
        try:
            key = str(filename.relative_to(ROOT))
        except ValueError:
            key = str(filename)
        counts[key] = counts.get(key, 0) + 1
    return ToolReport("ruff", sum(counts.values()), counts)


def collect_mypy() -> ToolReport:
    code, out, err = _run([sys.executable, "-m", "mypy", "src"])
    if code not in (0, 1):
        raise SystemExit(f"mypy failed to run (exit {code}): {err.strip()}")
    counts: dict[str, int] = {}
    for line in (out + "\n" + err).splitlines():
        match = _MYPY_RE.match(line.strip())
        if not match or match.group("level") != "error":
            continue
        path = Path(match.group("path"))
        if not path.is_absolute():
            path = (ROOT / path)
        try:
            key = str(path.resolve().relative_to(ROOT))
        except ValueError:
            key = str(path)
        counts[key] = counts.get(key, 0) + 1
    return ToolReport("mypy", sum(counts.values()), counts)


def load_baseline(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"total": 0, "files": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"total": 0, "files": {}}


def changed_python_files(base: str) -> set[str]:
    """Return tracked Python files changed vs ``base`` plus working-tree changes."""
    commands = [
        ["git", "diff", "--name-only", "--diff-filter=ACMR", base],
        ["git", "diff", "--name-only", "--diff-filter=ACMR"],
        ["git", "diff", "--name-only", "--cached", "--diff-filter=ACMR"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    files: set[str] = set()
    for command in commands:
        _code, out, _err = _run(command)
        for line in out.splitlines():
            line = line.strip()
            if line.endswith(".py"):
                files.add(line)
    return files


def _excluded(path: str) -> bool:
    return any(part in SKIP_PARTS for part in Path(path).parts)


def evaluate(
    report: ToolReport,
    baseline: dict[str, Any],
    *,
    changed: set[str] | None,
) -> list[str]:
    failures: list[str] = []
    baseline_total = int(baseline.get("total", 0))
    baseline_files: dict[str, int] = dict(baseline.get("files", {}))

    if report.total > baseline_total:
        failures.append(
            f"{report.name}: total {report.total} exceeds budget {baseline_total} "
            f"(+{report.total - baseline_total})"
        )

    for path, count in report.files.items():
        if _excluded(path):
            continue
        allowed = int(baseline_files.get(path, 0))
        if count > allowed:
            failures.append(
                f"{report.name}: {path} has {count} error(s), budget {allowed} "
                f"(+{count - allowed})"
            )

    if changed:
        for path in sorted(changed):
            if _excluded(path):
                continue
            current = int(report.files.get(path, 0))
            if not (ROOT / path).is_file():
                continue  # deleted file
            if current == 0:
                continue
            allowed = int(baseline_files.get(path, 0))
            if allowed == 0:
                failures.append(
                    f"{report.name}: changed/new file {path} must be clean, "
                    f"has {current} error(s)"
                )
            elif current > allowed:
                failures.append(
                    f"{report.name}: changed file {path} regressed "
                    f"{allowed} -> {current}"
                )
    return failures


def write_baseline(path: Path, report: ToolReport, *, allow_increase: bool) -> bool:
    previous = load_baseline(path)
    if report.total > int(previous.get("total", 0)) and not allow_increase:
        sys.stderr.write(
            f"refusing to raise {report.name} budget "
            f"{previous.get('total', 0)} -> {report.total} (use --allow-increase)\n"
        )
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **report.as_dict(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="rewrite the baselines")
    parser.add_argument(
        "--allow-increase", action="store_true",
        help="with --update: allow the total budget to grow (requires review)",
    )
    parser.add_argument(
        "--changed", default=None, metavar="BASE",
        help="also forbid regressions in files changed since git BASE",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    ruff = collect_ruff()
    mypy = collect_mypy()
    reports = [ruff, mypy]

    if args.update:
        ok = True
        ok &= write_baseline(RUFF_BASELINE, ruff, allow_increase=args.allow_increase)
        ok &= write_baseline(MYPY_BASELINE, mypy, allow_increase=args.allow_increase)
        if args.json:
            print(json.dumps({r.name: r.as_dict() for r in reports}, indent=2))
        else:
            print(f"ruff budget -> {ruff.total}, mypy budget -> {mypy.total}")
        return 0 if ok else 1

    changed = changed_python_files(args.changed) if args.changed else None
    failures: list[str] = []
    for report in reports:
        failures.extend(
            evaluate(
                report,
                load_baseline(RUFF_BASELINE if report.name == "ruff" else MYPY_BASELINE),
                changed=changed,
            )
        )

    summary = {
        "ruff": {**ruff.as_dict(), "budget": load_baseline(RUFF_BASELINE).get("total")},
        "mypy": {**mypy.as_dict(), "budget": load_baseline(MYPY_BASELINE).get("total")},
        "changed_files": sorted(changed) if changed is not None else None,
        "failures": failures,
        "passed": not failures,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for report in reports:
            budget = load_baseline(
                RUFF_BASELINE if report.name == "ruff" else MYPY_BASELINE
            ).get("total")
            state = "OK" if report.total <= int(budget or 0) else "OVER BUDGET"
            print(f"{report.name:5} {report.total:6} / budget {budget}  [{state}]")
        if changed is not None:
            print(f"changed files checked: {len(changed)}")
        if failures:
            print("\nQuality gate FAILED:")
            for failure in failures[:40]:
                print(f"  - {failure}")
            if len(failures) > 40:
                print(f"  ... and {len(failures) - 40} more")
            print("\nFix the regressions or (deliberately) refresh the budget with "
                  "--update after review.")
        else:
            print("Quality gate passed (budgeted debt, no regressions).")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
