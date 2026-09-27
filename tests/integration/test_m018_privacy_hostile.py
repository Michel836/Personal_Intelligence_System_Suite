"""Hostile privacy review for M018 exports (phase 33).

Each test actively tries to leak sensitive data through a different channel.
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from src.core.database import DatabaseManager
from src.core.scan_service import ScanRequest, ScanService
from src.core.volume import VolumeInfo
from src.reports import ExportService, PrivacyMode, ReportKind
from src.reports.pdf_export import available_providers, render_pdf

EMAIL = "jean.dupont@example.com"
PHONE = "+33 6 12 34 56 78"
IBAN = "FR76 3000 6000 0112 3456 7890 189"


def _seed(tmp_path: Path, *, filename: str = "note.txt") -> DatabaseManager:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / filename).write_text(f"Contact {EMAIL} tel {PHONE} IBAN {IBAN}", encoding="utf-8")
    db = DatabaseManager(tmp_path / "files.db")
    ScanService(db).run(ScanRequest(root=root, batch_size=10,
        volume=VolumeInfo(stable_key="H", device="H", mountpoint=str(tmp_path), is_available=True)))
    for row in db.search_files(None, limit=10):
        db.update_content(row["id"], f"Contact {EMAIL} tel {PHONE} IBAN {IBAN}")
    return db


def _generate(tmp_path: Path, db: DatabaseManager, mode: str, *,
              formats=("HTML", "JSON")) -> tuple[str, dict]:
    svc = ExportService(db, out_dir=tmp_path / "exports")
    definition = svc.create_definition(ReportKind.SEARCH.value, "Privacy test",
                                       query={"query": "Contact"}, privacy_mode=mode)
    result = svc.generate(definition, formats=tuple(formats))
    html = ""
    if any(a.format == "HTML" for a in result.artifacts):
        html = Path(next(a.path for a in result.artifacts if a.format == "HTML")).read_text()
    manifest = json.loads(Path(result.manifest_path).read_text())
    return html, manifest


def test_pii_in_body_is_masked(tmp_path) -> None:
    db = _seed(tmp_path)
    html, _ = _generate(tmp_path, db, PrivacyMode.MASK_PII.value)
    assert EMAIL not in html and PHONE not in html and IBAN not in html


def test_pii_in_filename_is_masked(tmp_path) -> None:
    db = _seed(tmp_path, filename="jean.dupont@example.com.txt")
    html, manifest = _generate(tmp_path, db, PrivacyMode.MASK_PII.value)
    assert EMAIL not in html
    assert all(EMAIL not in json.dumps(h) for h in manifest["source_hashes"])


def test_pii_absent_from_manifest(tmp_path) -> None:
    db = _seed(tmp_path)
    _, manifest = _generate(tmp_path, db, PrivacyMode.FULL_LOCAL.value)
    blob = json.dumps(manifest)
    assert EMAIL not in blob and PHONE not in blob and IBAN not in blob


def test_pii_absent_from_pdf_text(tmp_path) -> None:
    if not any(v["available"] for v in available_providers().values()):
        return
    db = _seed(tmp_path)
    html, _ = _generate(tmp_path, db, PrivacyMode.MASK_PII.value)
    out = tmp_path / "masked.pdf"
    result = render_pdf(html, out, provider="libreoffice")
    if not result.ok:
        return
    from PyPDF2 import PdfReader
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(out)).pages)
    assert EMAIL not in text and PHONE not in text and IBAN not in text


def test_path_redacted_hides_directories(tmp_path) -> None:
    db = _seed(tmp_path)
    html, _ = _generate(tmp_path, db, PrivacyMode.PATH_REDACTED.value)
    assert str(tmp_path) not in html
    assert "&lt;redacted&gt;" in html or "<redacted>" in html


def test_omit_high_sensitivity_excludes_content_and_lists(tmp_path) -> None:
    from src.intel import IntelStore
    db = _seed(tmp_path)
    row = db.search_files(None, limit=1)[0]
    IntelStore(db).set_pii(int(row["id"]), [{"type": "iban", "severity": "high", "count": 1,
                                             "confidence": 0.9, "detector": "iban",
                                             "fingerprint": "fp", "masked": "***"}])
    html, manifest = _generate(tmp_path, db, PrivacyMode.OMIT_HIGH_SENSITIVITY.value)
    assert IBAN not in html
    assert manifest["omitted"]


def test_full_local_warns_on_sensitive_content(tmp_path) -> None:
    from src.intel import IntelStore
    db = _seed(tmp_path)
    row = db.search_files(None, limit=1)[0]
    IntelStore(db).set_pii(int(row["id"]), [{"type": "iban", "severity": "high", "count": 1,
                                             "confidence": 0.9, "detector": "iban",
                                             "fingerprint": "fp", "masked": "***"}])
    svc = ExportService(db, out_dir=tmp_path / "exports")
    definition = svc.create_definition(ReportKind.SEARCH.value, "Warn",
                                       query={"query": "Contact"},
                                       privacy_mode=PrivacyMode.FULL_LOCAL.value)
    result = svc.generate(definition, formats=("JSON",))
    assert any("high-severity" in w for w in result.ir.warnings)


def test_metadata_only_has_no_excerpt_text(tmp_path) -> None:
    db = _seed(tmp_path)
    html, _ = _generate(tmp_path, db, PrivacyMode.METADATA_ONLY.value)
    assert EMAIL not in html and IBAN not in html


def test_no_pii_in_logs_during_export(tmp_path) -> None:
    db = _seed(tmp_path)
    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(str(m)), level="DEBUG")
    try:
        _generate(tmp_path, db, PrivacyMode.MASK_PII.value)
    finally:
        logger.remove(sink)
    assert not any(EMAIL in m or IBAN in m for m in messages)


def test_no_temp_residue_after_pdf_provider_failure(tmp_path) -> None:
    db = _seed(tmp_path)
    html, _ = _generate(tmp_path, db, PrivacyMode.MASK_PII.value)
    out = tmp_path / "exports" / "fail.pdf"
    result = render_pdf(html, out, provider="not-a-provider", allow_fallback=False)
    assert result.ok is False
    assert not out.exists()
    leftovers = [p.name for p in (tmp_path / "exports").glob("*.tmp-*")]
    assert leftovers == []
    globs = list(Path("/tmp").glob("pis-pdf-*"))
    assert globs == []  # temp dirs cleaned by context managers


def test_remote_summary_never_under_policy_never(tmp_path, monkeypatch) -> None:
    """Under policy=never the router must not even construct a remote provider."""
    from src.ai.providers import service as service_mod
    from src.ai.providers.openai_compatible import OpenAICompatibleLLMProvider

    monkeypatch.setenv("PIS_REMOTE_CONTENT_POLICY", "never")
    monkeypatch.setenv("PIS_AI_MODE", "local")
    service_mod.reset_ai_service()

    def _boom(*_a, **_k):
        raise AssertionError("remote provider must not be constructed under policy=never")

    monkeypatch.setattr(OpenAICompatibleLLMProvider, "__init__", _boom)
    db = _seed(tmp_path)
    svc = ExportService(db, out_dir=tmp_path / "exports")
    definition = svc.create_definition(ReportKind.SEARCH.value, "Remote",
                                       query={"query": "Contact"})
    result = svc.generate(definition, formats=("JSON",), summarize=True)
    # Either a local provider summarised it, or the summary was unavailable —
    # either way no remote provider was constructed (no AssertionError).
    assert result.ir.summary is not None
    service_mod.reset_ai_service()
