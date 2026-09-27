# ruff: noqa
"""OCR (Tesseract) concurrency benchmark over synthetic text images."""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bench.common import ResourceSampler, json_print, load_conditions, wipe  # noqa: E402


def build_images(root: Path, count: int) -> list[Path]:
    from PIL import Image, ImageDraw

    root.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(count):
        img = Image.new("RGB", (600, 200), "white")
        d = ImageDraw.Draw(img)
        d.text((10, 80), f"Contrat numero {i} facture client service", fill="black")
        p = root / f"scan_{i:05d}.png"
        img.save(p)
        made.append(p)
    return made


def run(paths, workers):
    from src.extractors.ocr import ocr_file

    ok = 0
    chars = 0
    with ResourceSampler() as s:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(ocr_file, p) for p in paths]
            for f in as_completed(futs):
                r = f.result()
                ok += int(r.success)
                chars += len(r.content or "")
    return {
        "workers": workers,
        "pages": len(paths),
        "ok": ok,
        "chars": chars,
        "wall_s": round(s.sample.wall, 3),
        "pages_per_sec": round(len(paths) / s.sample.wall, 2) if s.sample.wall else 0,
        "cpu_pct": round(s.sample.cpu_pct, 1),
        "rss_mb": round(s.sample.rss_mb, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="/tmp/pis_bench/ocr")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--workers", default="1,2,4,8")
    ap.add_argument("--regen", action="store_true")
    args = ap.parse_args()
    os.environ.setdefault("PIS_OCR_ENABLED", "1")
    os.environ.setdefault("PIS_OCR_LANGS", "eng")

    root = Path(args.images)
    if args.regen or not root.exists():
        wipe(root)
        build_images(root, args.count)
    paths = sorted(p for p in root.iterdir() if p.suffix == ".png")
    report = {"conditions": load_conditions(), "images": len(paths), "results": []}
    for w in [int(x) for x in args.workers.split(",") if x.strip()]:
        report["results"].append(run(paths, w))
    json_print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
