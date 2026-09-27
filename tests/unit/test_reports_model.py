"""Report model, citation, provenance and privacy units (M018)."""
from __future__ import annotations

from src.core.database import DatabaseManager
from src.reports.citations import (
    CitationRegistry,
    citation_with_location,
    extract_citations,
)
from src.reports.models import (
    Block,
    BlockType,
    PrivacyMode,
    ProvenanceClass,
    ReportDefinition,
    ReportIR,
    Section,
)
from src.reports.privacy import (
    all_mode_descriptions,
    filter_documents,
    mask_text,
    safe_path,
)
from src.reports.provenance import build_source, resolve_date


def _insert_file(db: DatabaseManager, file_id: int, path: str, *, size: int = 10,
                 state: str = "ACTIVE", modified: str = "2024-02-01 10:00:00") -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO files (id, path, filename, extension, size_bytes, modified_at, "
            "state, document_kind, content_extracted) VALUES (?, ?, ?, '.txt', ?, ?, ?, "
            "'PHYSICAL_FILE', 0)",
            (file_id, path, path.rsplit("/", 1)[-1], size, modified, state))
        conn.commit()


# --- citations ---------------------------------------------------------------
def test_citation_registry_is_deterministic_and_validated() -> None:
    reg = CitationRegistry()
    a = reg.document(10, label="a.txt")
    b = reg.document(20, label="b.txt")
    assert (a.ref, b.ref) == ("D1", "D2")
    assert reg.document(10).ref == "D1"  # stable per file id
    assert reg.ref_for_document(10) == "D1"
    assert reg.validate("[D1] and [D2] fine") == []
    assert reg.validate("[D9] dangling") == ["D9"]
    reg.entity("acme")
    reg.version_family("vf-1")
    kinds = {s.kind for s in reg.sources()}
    assert {"document", "entity", "version_family"} <= kinds
    assert reg.appendix()[0]["ref"] == "D1"


def test_citation_location_only_when_real() -> None:
    assert citation_with_location("D3", None) == "[D3]"
    assert citation_with_location("D3", "4") == "[D3:p4]"
    assert citation_with_location("D3", "p7") == "[D3:p7]"
    assert citation_with_location("D3", "section-2") == "[D3]"
    assert extract_citations("see [D1:p2] and [E4] and [D1]") == ["D1", "E4"]


# --- provenance --------------------------------------------------------------
def test_provenance_date_and_unavailable(tmp_path) -> None:
    db = DatabaseManager(tmp_path / "db.db")
    _insert_file(db, 1, "/data/report.txt", modified="2023-05-06 08:00:00")
    # A date marker in the filename is INFERRED, never KNOWN.
    _insert_file(db, 2, "/data/rapport_2021-07-09_v2.txt")
    reg = CitationRegistry()
    s1 = build_source(reg, db, 1, PrivacyMode.FULL_LOCAL.value)
    date, source, cls = resolve_date(db, {"id": 1, "path": "/data/report.txt",
                                          "modified_at": "2023-05-06 08:00:00"})
    assert date == "2023-05-06" and source == "modified_at" and cls == ProvenanceClass.KNOWN.value
    s2 = build_source(reg, db, 2, PrivacyMode.FULL_LOCAL.value)
    assert s2.date_source == "filename_version_marker"
    assert s2.date_class == ProvenanceClass.INFERRED.value
    # A missing row is registered UNAVAILABLE, never fabricated.
    s3 = build_source(reg, db, 999, PrivacyMode.FULL_LOCAL.value)
    assert s3.unavailable is True and s3.provenance == ProvenanceClass.UNAVAILABLE.value
    assert s1.extraction_state in {"NOT_EXTRACTED", "PENDING"}


# --- privacy -----------------------------------------------------------------
def test_privacy_modes_are_described() -> None:
    described = {d["mode"] for d in all_mode_descriptions()}
    assert described == {m.value for m in PrivacyMode}
    assert len(described) == 5


def test_mask_text_and_safe_path() -> None:
    raw = "write to jean.dupont@example.com or +33 6 12 34 56 78"
    masked = mask_text(raw, PrivacyMode.MASK_PII.value)
    assert "jean.dupont@example.com" not in masked
    assert mask_text(raw, PrivacyMode.FULL_LOCAL.value) == raw
    assert safe_path("/home/secret/dir/jean.dupont@example.com.pdf",
                     PrivacyMode.PATH_REDACTED.value) == "<redacted>/jean.dupont@example.com.pdf"
    pii_path = safe_path("/home/secret/jean.dupont@example.com.pdf",
                         PrivacyMode.MASK_PII.value)
    assert "jean.dupont@example.com" not in pii_path
    assert safe_path(None, PrivacyMode.FULL_LOCAL.value) is None


def test_omit_high_sensitivity_filters_documents(tmp_path) -> None:
    from src.intel import IntelStore
    db = DatabaseManager(tmp_path / "db.db")
    _insert_file(db, 1, "/a.txt")
    _insert_file(db, 2, "/b.txt")
    store = IntelStore(db)
    store.set_pii(1, [{"type": "iban", "severity": "high", "count": 1, "confidence": 0.9,
                       "detector": "iban", "fingerprint": "fp", "masked": "***"}])
    kept, omitted = filter_documents(db, [1, 2], PrivacyMode.OMIT_HIGH_SENSITIVITY.value)
    assert kept == [2]
    assert omitted and omitted[0]["file_id"] == 1 and omitted[0]["reason"]
    kept_all, omitted_none = filter_documents(db, [1, 2], PrivacyMode.FULL_LOCAL.value)
    assert kept_all == [1, 2] and omitted_none == []


# --- IR reproducibility ------------------------------------------------------
def _ir(definition: ReportDefinition, text: str) -> ReportIR:
    ir = ReportIR(definition=definition)
    ir.sections = [Section(id="s1", title="S", blocks=[Block(BlockType.PARAGRAPH.value, {"text": text})])]
    return ir


def test_logical_fingerprint_is_stable_and_content_sensitive() -> None:
    d = ReportDefinition(report_id="r1", kind="SEARCH", title="T")
    a = _ir(d, "hello world")
    b = _ir(d, "hello world")
    a.generated_at = "2020-01-01 00:00:00"
    b.generated_at = "2030-01-01 00:00:00"
    assert a.logical_fingerprint() == b.logical_fingerprint()
    c = _ir(d, "hello changed")
    assert c.logical_fingerprint() != a.logical_fingerprint()


def test_definition_json_roundtrip() -> None:
    d = ReportDefinition(report_id="r1", kind="DOSSIER", title="T", description="D",
                         query={"query": "x"}, document_ids=[1, 2],
                         privacy_mode=PrivacyMode.MASK_PII.value, options={"excerpts": True})
    restored = ReportDefinition.from_dict(d.as_dict())
    assert restored.as_dict() == d.as_dict()
