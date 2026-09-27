"""M020 privacy: no raw PII in labels, context or topic evidence."""
from __future__ import annotations

from src.galaxy.topics import label_from_evidence

RAW_EMAIL = "jean.dupont@example.com"


def test_topic_labels_never_leak_raw_pii(galaxy_env) -> None:
    galaxy_env.db.update_content(1, f"finance invoice bank contact {RAW_EMAIL} accounting")
    service = galaxy_env.service
    run_id = service.build_clusters(scope={"kind": "all"}, k=5, persist=True)["run_id"]
    topics = service.build_topics(run_id)
    for topic in topics:
        assert RAW_EMAIL not in topic.label
        assert "@" not in topic.label
        for term, _weight in topic.terms:
            assert "@" not in term


def test_label_builder_excludes_person_and_masks() -> None:
    label = label_from_evidence(
        [("invoice", 2.0)],
        [{"type": "PERSON", "display": "Jean Dupont"},
         {"type": "EMAIL", "display": "j***@example.com"}],
        [], 3)
    assert "Jean" not in label
    assert "invoice" in label


def test_document_context_only_returns_masked_pii(galaxy_env) -> None:
    from src.intel import IntelStore
    store = IntelStore(galaxy_env.db)
    store.set_pii(1, [{"type": "email", "severity": "medium", "count": 1,
                       "confidence": 0.95, "detector": "email",
                       "fingerprint": "abc123", "masked": "j***@example.com"}])
    context = galaxy_env.service.document_context(1)
    findings = context["intel"]["pii"]
    assert findings
    assert findings[0]["masked"] == "j***@example.com"
    assert RAW_EMAIL not in str(context)
