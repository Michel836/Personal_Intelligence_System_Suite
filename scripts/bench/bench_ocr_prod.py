# ruff: noqa
"""Production-style OCR concurrency check with system monitoring.

Generates full-page (1240x1754, ~150 dpi) text images and runs the real
``src.extractors.ocr.ocr_file`` path at several worker counts while sampling:

* system-wide CPU (all cores) and iowait;
* RAM / swap;
* context-switch rate (/proc/stat ctxt);
* scheduler responsiveness (latency of a trivial /bin/true spawn);
* per-page OCR latency (p50/p95/max).
"""
from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bench.common import json_print, load_conditions, wipe  # noqa: E402


def _read_cpu():
    with open("/proc/stat") as fh:
        parts = [int(x) for x in fh.readline().split()[1:]]
    total = sum(parts)
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    iowait = parts[4] if len(parts) > 4 else 0
    return total, idle, iowait


def _read_ctxt():
    with open("/proc/stat") as fh:
        for line in fh:
            if line.startswith("ctxt"):
                return int(line.split()[1])
    return 0


class Monitor:
    def __init__(self, interval=0.3):
        self.interval = interval
        self.stop = threading.Event()
        self.thread = None
        self.resp_ms = []
        self.ram_mb = []
        self.swap_mb = []
        self.samples = 0

    def _probe(self):
        t = time.perf_counter()
        subprocess.run(["/bin/true"], check=False)
        return (time.perf_counter() - t) * 1000

    def _loop(self):
        try:
            import psutil

            proc = psutil
        except Exception:
            proc = None
        while not self.stop.is_set():
            self.resp_ms.append(self._probe())
            if proc is not None:
                vm = proc.virtual_memory()
                sm = proc.swap_memory()
                self.ram_mb.append(vm.used / 1e6)
                self.swap_mb.append(sm.used / 1e6)
            self.samples += 1
            self.stop.wait(self.interval)

    def start(self):
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def finish(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)

    def p95(self, values):
        if not values:
            return 0.0
        s = sorted(values)
        return round(s[max(0, int(len(s) * 0.95) - 1)], 2)


def build_images(root: Path, count: int) -> list[Path]:
    from PIL import Image, ImageDraw, ImageFont

    root.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    words = ("le contrat de service prevoit une clause de confidentialite et un "
             "delai de paiement de trente jours facture client fournisseur").split()
    made = []
    for i in range(count):
        img = Image.new("RGB", (1240, 1754), "white")
        d = ImageDraw.Draw(img)
        y = 40
        for row in range(58):
            line = " ".join(words[(row + j + i) % len(words)] for j in range(11))
            d.text((40, y), line, fill="black", font=font)
            y += 28
        p = root / f"page_{i:03d}.png"
        img.save(p)
        made.append(p)
    return made


def run(paths, workers, langs):
    from src.extractors.ocr import ocr_file

    monitor = Monitor()
    wall_start = time.perf_counter()
    total0, idle0, iowait0 = _read_cpu()
    c0 = _read_ctxt()
    monitor.start()
    lat = []
    ok = 0
    chars = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(ocr_file, p, langs=langs): p for p in paths}
        for f in as_completed(futs):
            r = f.result()
            lat.append(r.extraction_time)
            ok += int(r.success)
            chars += len(r.content or "")
    wall = time.perf_counter() - wall_start
    total1, idle1, iowait1 = _read_cpu()
    monitor.finish()
    c1 = _read_ctxt()
    dt = total1 - total0
    cpu_pct = round((1 - (idle1 - idle0) / dt) * 100, 1) if dt else 0
    iowait_pct = round((iowait1 - iowait0) / dt * 100, 2) if dt else 0
    try:
        import psutil

        load = [round(x, 2) for x in psutil.getloadavg()]
        ncpu = psutil.cpu_count() or 1
    except Exception:
        load, ncpu = [], os.cpu_count() or 1
    lat_sorted = sorted(lat)
    return {
        "workers": workers,
        "pages": len(paths),
        "ok": ok,
        "chars": chars,
        "wall_s": round(wall, 3),
        "pages_per_sec": round(len(paths) / wall, 2) if wall else 0,
        "system_cpu_pct": cpu_pct,
        "iowait_pct": iowait_pct,
        "loadavg_after": load,
        "cpu_count": ncpu,
        "ctxt_per_sec": round((c1 - c0) / wall, 0) if wall else 0,
        "ram_used_max_mb": round(max(monitor.ram_mb), 1) if monitor.ram_mb else 0,
        "swap_used_max_mb": round(max(monitor.swap_mb), 1) if monitor.swap_mb else 0,
        "resp_p50_ms": round(statistics.median(monitor.resp_ms), 2) if monitor.resp_ms else 0,
        "resp_p95_ms": monitor.p95(monitor.resp_ms),
        "resp_max_ms": round(max(monitor.resp_ms), 2) if monitor.resp_ms else 0,
        "page_p50_s": round(statistics.median(lat), 3) if lat else 0,
        "page_p95_s": round(lat_sorted[max(0, int(len(lat) * 0.95) - 1)], 3) if lat else 0,
        "page_max_s": round(max(lat), 3) if lat else 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="/tmp/pis_bench/ocr_prod")
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--workers", default="8,16,24")
    ap.add_argument("--langs", default=os.environ.get("PIS_OCR_LANGS", "fra+deu+eng"))
    ap.add_argument("--regen", action="store_true")
    args = ap.parse_args()
    os.environ.setdefault("PIS_OCR_ENABLED", "1")
    root = Path(args.images)
    if args.regen or not root.exists():
        wipe(root)
        build_images(root, args.count)
    paths = sorted(root.glob("*.png"))
    report = {"conditions": load_conditions(), "images": len(paths),
              "langs": args.langs, "results": []}
    # Warm tesseract + page cache.
    run(paths[: min(2, len(paths))], 1, args.langs)
    for w in [int(x) for x in args.workers.split(",") if x.strip()]:
        report["results"].append(run(paths, w, args.langs))
    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
