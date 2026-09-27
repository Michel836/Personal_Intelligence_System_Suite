"""Citation-grounded, policy-aware summary units (M018, phases 20-21)."""
from __future__ import annotations

from dataclasses import dataclass

from src.core.database import DatabaseManager
from src.reports.citations import CitationRegistry
from src.reports.models import PrivacyMode, ReportDefinition, ReportIR
from src.reports.provenance import build_source
from src.reports.summary import ReportSummarizer


@dataclass
class _Info:
    provider: str = "fake"
    model: str = "fake-1"
    remote: bool = False


@dataclass
class _Result:
    text: str
    provider: str = "fake"
    model: str = "fake-1"


class _FakeProvider:
    def __init__(self, text: str, *, available: bool = True, error: Exception | None = None) -> None:
        self.text = text
        self.available = available
        self.error = error
        self.last_messages: list[dict[str, str]] = []

    def is_available(self) -> bool:
        return self.available

    def model_info(self) -> _Info:
        return _Info()

    def chat(self, messages, *, options=None):  # noqa: ARG002 - provider interface
        self.last_messages = list(messages)
        if self.error is not None:
            raise self.error
        return _Result(self.text)


def _add(db: DatabaseManager, fid: int, text: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO files (id, path, filename, extension, size_bytes, modified_at, "
            "state, document_kind, content_extracted) VALUES (?, ?, ?, '.txt', 10, "
            "'2024-01-01 00:00:00', 'ACTIVE', 'PHYSICAL_FILE', 1)",
            (fid, f"/c/{fid}.txt", f"{fid}.txt"))
        conn.commit()
    db.update_content(fid, text)


def _ir(db: DatabaseManager, ids: list[int], mode: str = PrivacyMode.FULL_LOCAL.value) -> ReportIR:
    reg = CitationRegistry()
    ir = ReportIR(definition=ReportDefinition(report_id="r", kind="SEARCH", title="T",
                                              privacy_mode=mode))
    for fid in ids:
        build_source(reg, db, fid, mode)
    ir.sources = reg.sources()
    return ir


def test_grounded_summary_keeps_only_provided_refs(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "alpha")
    _add(db, 2, "beta")
    provider = _FakeProvider("Alpha and beta agree [D1][D2]. Fabricated claim [D9].")
    result = ReportSummarizer(db, provider=provider).summarize(_ir(db, [1, 2]))
    assert result.available and result.label == "AI-generated summary"
    refs = [r for p in result.paragraphs for r in p["refs"]]
    assert set(refs) == {"D1", "D2"}
    assert "D9" not in refs  # never cites a source it did not receive


def test_unavailable_provider_is_not_fatal(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "alpha")
    provider = _FakeProvider("x", available=False)
    result = ReportSummarizer(db, provider=provider).summarize(_ir(db, [1]))
    assert result.available is False and result.error


def test_remote_blocked_is_surfaced_not_bypassed(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "alpha")
    blocker = type("RemoteContentBlockedError", (Exception,), {})
    provider = _FakeProvider("x", error=blocker("blocked"))
    result = ReportSummarizer(db, provider=provider).summarize(_ir(db, [1]))
    assert result.available is False
    assert "policy" in (result.error or "").lower()


def test_mask_pii_never_sends_raw_identifiers(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _add(db, 1, "contact jean.dupont@example.com or +33 6 12 34 56 78")
    provider = _FakeProvider("Summary [D1].")
    result = ReportSummarizer(db, provider=provider).summarize(
        _ir(db, [1], mode=PrivacyMode.MASK_PII.value))
    assert result.available
    prompt = "\n".join(m["content"] for m in provider.last_messages)
    assert "jean.dupont@example.com" not in prompt
    assert "+33 6 12 34 56 78" not in prompt


def test_no_sources_is_insufficient(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    provider = _FakeProvider("anything [D1]")
    result = ReportSummarizer(db, provider=provider).summarize(ReportIR(
        definition=ReportDefinition(report_id="r", kind="SEARCH", title="T")))
    assert result.available is False and result.insufficient_evidence
