"""Optional pgvector backend + decision + migration plan (M019)."""
from __future__ import annotations

import json

from src.ops import pgvector


def _fake_store(base) -> None:
    store = base / "model-x"
    store.mkdir(parents=True)
    (store / "meta.json").write_text(json.dumps(
        {"model_key": "model-x", "dim": 1024, "count": 80039}))
    (store / "matrix.npy").write_bytes(b"\x00" * 128)


def test_availability_requires_configured_server(monkeypatch) -> None:
    monkeypatch.delenv("PIS_PG_URL", raising=False)
    probed = pgvector.pgvector_available()
    assert probed["available"] is False
    assert "not configured" in probed["reason"] or "missing" in probed["reason"]
    assert "://" not in probed["url"] or "***" in probed["url"] or probed["url"] == "(unset)"


def test_resolve_backend_falls_back_to_matrix(monkeypatch) -> None:
    monkeypatch.delenv("PIS_PG_URL", raising=False)
    default = pgvector.resolve_vector_backend()
    assert default["backend"] == pgvector.MATRIX and default["fallback"] is False
    forced = pgvector.resolve_vector_backend(configured="pgvector")
    assert forced["backend"] == pgvector.MATRIX and forced["fallback"] is True


def test_decision_keeps_current_without_evidence() -> None:
    decision = pgvector.decide(benchmark_result={"available": False})
    assert decision["decision"] == "KEEP_CURRENT"
    assert decision["canonical_metadata"] == "sqlite"


def test_migration_plan_and_dry_run(tmp_path) -> None:
    _fake_store(tmp_path)
    plan = pgvector.migration_plan(tmp_path)
    assert plan["stores"] and plan["stores"][0]["model_key"] == "model-x"
    assert plan["dry_run_default"] is True
    result = pgvector.export_to_pgvector(store_base=tmp_path, dry_run=True)
    assert result["status"] == "PLAN" and result["target"]["count"] == 80039


def test_rollback_requires_confirmation() -> None:
    assert pgvector.rollback_pgvector(confirm=False)["status"] == "REFUSED"
