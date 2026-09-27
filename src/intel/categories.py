"""Configurable, bounded document categorisation (M015).

Two complementary signals:

* deterministic **structural** categories from the file extension/type;
* **content/topic** categories from a configurable keyword taxonomy plus an
  optional semantic similarity against category descriptions (using the existing
  embedding store — no per-document LLM call).

Manual user overrides always win; they are applied by the pipeline, not here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_STRUCTURAL = {
    ".pdf": "document_pdf", ".doc": "document_office", ".docx": "document_office",
    ".odt": "document_office", ".rtf": "document_office", ".ods": "document_office",
    ".xls": "spreadsheet", ".xlsx": "spreadsheet", ".csv": "spreadsheet",
    ".ppt": "presentation", ".pptx": "presentation", ".odp": "presentation",
    ".eml": "email", ".msg": "email", ".pst": "email", ".ost": "email",
    ".txt": "text", ".md": "text", ".rst": "text",
    ".py": "source_code", ".js": "source_code", ".ts": "source_code", ".java": "source_code",
    ".c": "source_code", ".cpp": "source_code", ".h": "source_code", ".cs": "source_code",
    ".go": "source_code", ".rs": "source_code", ".rb": "source_code", ".php": "source_code",
    ".sql": "source_code", ".sh": "source_code", ".json": "structured_data", ".xml": "structured_data",
    ".yaml": "structured_data", ".yml": "structured_data",
    ".zip": "archive", ".rar": "archive", ".7z": "archive", ".tar": "archive", ".gz": "archive",
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image", ".tiff": "image",
    ".mp3": "audio", ".wav": "audio", ".flac": "audio", ".m4a": "audio",
    ".mp4": "video", ".mkv": "video", ".avi": "video", ".mov": "video",
}

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ_]+", re.UNICODE)


def default_taxonomy_path() -> Path:
    return Path(__file__).with_name("taxonomy.json")


class CategoryEngine:
    def __init__(self, taxonomy_path: Path | None = None) -> None:
        self.taxonomy_path = Path(taxonomy_path) if taxonomy_path else default_taxonomy_path()
        self.categories: list[dict[str, Any]] = []
        self._compiled: dict[str, list[re.Pattern[str]]] = {}
        self.load()

    def load(self) -> None:
        data = json.loads(self.taxonomy_path.read_text(encoding="utf-8"))
        self.categories = list(data.get("categories", []))
        self._compiled = {}
        for cat in self.categories:
            patterns = [re.compile(r"(?<![\w])" + re.escape(k.lower()) + r"(?![\w])") for k in cat.get("keywords", [])]
            self._compiled[cat["name"]] = patterns

    def add_category(self, name: str, keywords: list[str], *, description: str = "") -> None:
        self.categories.append({"name": name, "description": description, "keywords": keywords})
        self._compiled[name] = [re.compile(re.escape(k.lower())) for k in keywords]

    def structural_category(self, extension: str | None) -> str | None:
        return _STRUCTURAL.get((extension or "").lower())

    def classify(self, text: str, *, extension: str | None = None,
                 doc_vector: Any = None, category_vectors: dict[str, Any] | None = None,
                 keyword_threshold: float = 1.0, semantic_threshold: float = 0.3,
                 top_k: int = 3) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        structural = self.structural_category(extension)
        if structural:
            out.append({"category": structural, "score": 1.0, "source": "structural"})

        low = (text or "").lower()
        tokens = _TOKEN_RE.findall(low)
        token_set = set(tokens)
        token_count = max(len(tokens), 1)
        keyword_scores: dict[str, float] = {}
        for cat in self.categories:
            hits = 0
            for kw in cat.get("keywords", []):
                k = kw.lower()
                # Single tokens use an O(1) set lookup; multi-word phrases use a
                # bounded substring check.
                if " " in k:
                    hits += 1 if k in low else 0
                elif k in token_set:
                    hits += 1
            if hits:
                keyword_scores[cat["name"]] = hits / token_count * 100.0
        for name, score in sorted(keyword_scores.items(), key=lambda kv: kv[1], reverse=True):
            if score >= keyword_threshold:
                out.append({"category": name, "score": round(min(score, 1.0), 3), "source": "keyword"})

        if doc_vector is not None and category_vectors:
            import numpy as np
            q = np.asarray(doc_vector, dtype=np.float32)
            qn = float(np.linalg.norm(q)) or 1.0
            for name, vec in category_vectors.items():
                v = np.asarray(vec, dtype=np.float32)
                sim = float(np.dot(q, v) / (qn * (float(np.linalg.norm(v)) or 1.0)))
                if sim >= semantic_threshold:
                    out.append({"category": name, "score": round(sim, 3), "source": "semantic"})

        # Deduplicate by category keeping the best score/source preference.
        best: dict[str, dict[str, Any]] = {}
        for item in out:
            cur = best.get(item["category"])
            if cur is None or item["score"] > cur["score"]:
                best[item["category"]] = item
        ranked = sorted(best.values(), key=lambda d: d["score"], reverse=True)
        topic = [d for d in ranked if d["source"] != "structural"][:top_k]
        structural_items = [d for d in ranked if d["source"] == "structural"]
        return structural_items + topic
