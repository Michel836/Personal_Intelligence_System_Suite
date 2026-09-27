# ruff: noqa
"""Extraction pipeline benchmark: sequential vs ThreadPool vs ProcessPool."""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bench.common import (  # noqa: E402
    ResourceSampler,
    generate_documents,
    json_print,
    load_conditions,
    make_docx,
    make_odt,
    make_pdf,
    make_xlsx,
    wipe,
)


def build_fixtures(root: Path, count: int) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    generate_documents(root, count)
    extra = max(1, count // 6)
    for i in range(extra):
        try:
            make_pdf(root / f"doc_pdf_{i}.pdf", pages=1)
            make_docx(root / f"doc_docx_{i}.docx")
            make_xlsx(root / f"doc_xlsx_{i}.xlsx")
            make_odt(root / f"doc_odt_{i}.odt")
        except Exception:
            pass
    return sorted(p for p in root.iterdir() if p.is_file())


def _extract_one(path_str: str):
    from src.extractors.manager import ExtractionManager

    mgr = _worker_manager()
    result = mgr.extract_single(Path(path_str))
    return bool(result.success), len(result.content or "")


_WORKER_MGR = None


def _worker_manager():
    global _WORKER_MGR
    if _WORKER_MGR is None:
        from src.extractors.manager import ExtractionManager

        _WORKER_MGR = ExtractionManager(max_workers=1)
    return _WORKER_MGR


def run_sequential(paths: list[Path]):
    from src.extractors.manager import ExtractionManager

    mgr = ExtractionManager(max_workers=1)
    ok = 0
    total_chars = 0
    with ResourceSampler() as s:
        for p in paths:
            r = mgr.extract_single(p)
            ok += int(r.success)
            total_chars += len(r.content or "")
    return _summary("sequential", 0, len(paths), ok, total_chars, s)


def run_threads(paths: list[Path], workers: int):
    from src.extractors.manager import ExtractionManager

    mgr = ExtractionManager(max_workers=workers)
    ok = 0
    total_chars = 0
    with ResourceSampler() as s:
        results = mgr.extract_batch(paths)
    for r in results.values():
        ok += int(r.success)
        total_chars += len(r.content or "")
    return _summary("threads", workers, len(paths), ok, total_chars, s)


def run_processes(paths: list[Path], workers: int):
    ok = 0
    total_chars = 0
    with ResourceSampler() as s:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_extract_one, str(p)) for p in paths]
            for f in as_completed(futures):
                good, nchars = f.result()
                ok += int(good)
                total_chars += nchars
    return _summary("processes", workers, len(paths), ok, total_chars, s)


def _summary(kind, workers, n, ok, chars, s):
    return {
        "kind": kind,
        "workers": workers,
        "docs": n,
        "ok": ok,
        "chars": chars,
        "wall_s": round(s.sample.wall, 3),
        "docs_per_sec": round(n / s.sample.wall, 1) if s.sample.wall else 0,
        "cpu_pct": round(s.sample.cpu_pct, 1),
        "rss_mb": round(s.sample.rss_mb, 1),
        "iowait_pct": getattr(s, "iowait_pct", 0.0),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="/tmp/pis_bench/extract")
    ap.add_argument("--count", type=int, default=120)
    ap.add_argument("--workers", default="1,2,4,8,16")
    ap.add_argument("--modes", default="sequential,threads")
    ap.add_argument("--regen", action="store_true")
    args = ap.parse_args()

    root = Path(args.fixtures)
    if args.regen or not root.exists():
        wipe(root)
        build_fixtures(root, args.count)
    paths = sorted(p for p in root.iterdir() if p.is_file())
    report = {"conditions": load_conditions(), "fixtures": len(paths), "results": []}
    modes = set(args.modes.split(","))
    # Warm imports + page cache so the first measured run is not penalised.
    run_sequential(paths)
    if "sequential" in modes:
        report["results"].append(run_sequential(paths))
    for w in [int(x) for x in args.workers.split(",") if x.strip()]:
        if "threads" in modes:
            report["results"].append(run_threads(paths, w))
        if "processes" in modes:
            report["results"].append(run_processes(paths, w))
    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
