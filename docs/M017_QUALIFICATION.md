# M017 Qualification Report — Email, Legacy, OCR Hardening & Error Queue

**Status:** QUALIFIED (local, bounded, evidence-backed)
**Branch:** `feat/m001-validation-harness` (no push)
**Base HEAD:** `308a707` · M017 work is uncommitted on top of it
**Evidence:** the most recent `.validation/<UTC run>/` directory (its
`validation.json` carries the `validated_state_sha256` bound to the complete
final state, including this report) plus `/home/chu/.pis-trials/m017/evidence/`.
**Tree:** DIRTY (M017 is intentionally uncommitted; the fingerprint binds staged,
unstaged and untracked changes)

---

## 1. Scope

M017 closes the real-world ingestion gaps: `.eml`/`.msg` email, legacy Office
(`.doc/.xls/.ppt`) + RTF, EPUB, CHM, hardened opt-in OCR, a canonical extraction
outcome taxonomy, a persistent error/retry queue, email threading, and a
capability/status view in the UI. It is local-only: no cloud conversion, no
source modification, no mandatory external service.

## 2. Phase results

| Phase | Result | Evidence |
|---|---|---|
| UI ingestion / error workflow | ✅ render, bounded run, issue surfacing, ignore | `tests/ui/test_ingest_acceptance.py` (2) |
| Capability / status view | ✅ live matrix + missing-tool report + OCR languages | `capability_matrix()`, `test_capability_matrix_reports_missing` |
| Real bounded benchmark | ✅ 279 + 396 real documents | `ingest_bench.json`, `ingest_msg.json` |
| Email/legacy/OCR quality benchmark | ✅ synthetic recall 1.0 · OCR 0.981 | `quality.json` (this report §4) |
| Incremental freshness | ✅ modified email invalidated + re-ingested only | `test_m017_integration_quality.py::test_modified_email_is_reingested_incrementally` |
| Graph / intelligence integration | ✅ `EMAIL_REPLY_TO` + language + masked PII | `test_email_thread_relation_and_graph`, `test_email_intelligence_language_and_masked_pii` |
| Privacy checks | ✅ no addresses/PII in logs, queue, audit | `test_queue_and_audit_never_store_sensitive_payloads` |
| Hostile review | ✅ 4 defects found and repaired | §5 |
| Full regression | ✅ 531 collected, green | `.validation/<latest>/pytest.stdout.txt` |
| Documentation | ✅ product doc + gap matrix + this report | `docs/M017_INGESTION.md`, gap matrix X5–X8/X13/X15 |
| Final qualification report | ✅ this document | — |

## 3. Functional evidence

28 M017 tests, all green:

```
tests/unit/test_ingest_email_legacy.py            9
tests/unit/test_ingest_ocr.py                     4
tests/unit/test_ingest_taxonomy_queue.py          6
tests/integration/test_m017_ingestion_freshness.py 4
tests/integration/test_m017_integration_quality.py 3
tests/ui/test_ingest_acceptance.py                2
```

The full suite is green: **531 tests collected**, 0 failures, 5 intentional
AI-provider skips (unchanged from the baseline).

## 4. Measured quality (aggregate only)

From `scripts/bench/m017_quality.py`:

* **Synthetic fidelity** — EML plain/HTML/nested/attachment, MSG (native CFB),
  EPUB and RTF each yield the expected token (recall **1.0**); the attachment
  payload is **not** leaked into the body.
* **OCR character accuracy** — 3 synthetic images (eng/deu/fra): mean similarity
  **0.981**.
* **Real read-only sample** — MSG 20/20, EML 3/3, DOC 6/6, XLS 8/12 (4 legit
  no-text), RTF 6/6, CHM 20/20, EPUB 20/20; mean printable ratio 0.975–1.000.

The real bounded benchmark (`ingest_bench.json`, `ingest_msg.json`) extracted
**675 real documents**: MSG 192/192, EML 3/3, DOC 6/6, XLS 8/12, RTF 6/6,
CHM 42/42, EPUB 400/400, OCR 10/10, at ~500 MB peak RSS.

## 5. Hostile review

| # | Finding | Severity | Repair |
|---|---|---|---|
| 1 | Attachments recorded **twice** (`msg.walk()` *and* manual recursion) | major | single traversal + regression assertion |
| 2 | Nested `message/rfc822` body silently dropped | major | per-depth body assembly, bounded by `MAX_NESTED_DEPTH` |
| 3 | `OCR_REQUIRED` (not documented retryable) auto-retried immediately via a `NULL` backoff | major | retry selector honours the documented retryable set; regression test |
| 4 | Unbounded reads (EPUB entry, CHM on-disk, LibreOffice text) | minor | size guards added before reading |
| — | `Dict`/`Any` undefined names, CHM `None` arg | minor | corrected (also removes the new ruff/mypy findings) |

Residual risks (documented, not hidden): PST/OST remain
`UNSUPPORTED (dependency)` because `readpst`/`libpff`/`pypff` are absent; a
CHM/zip bomb is bounded by the 90 s timeout and the post-extraction size cap
rather than an up-front header check.

## 6. Regression gates

| Gate | Result | Note |
|---|---|---|
| repository audit | PASS | declared entrypoints verified |
| compileall | PASS | |
| pytest | PASS | 531 collected, green |
| `git diff --check` | PASS | |
| ruff | FAIL (baseline) | 6998 errors vs **7052** at baseline: **−54**; **0** in M017 files |
| mypy | FAIL (baseline) | 1137 errors / 65 files vs **1147 / 66** at baseline: **−10**; **0** in M017 files |

The red ruff/mypy gates are the long-standing repository-wide debt present in
every prior `.validation/` run (e.g. the `20260927T142145Z` baseline). M017 changes the debt
**downward** and introduces **no new finding** in any new or touched file.
Per the fail-closed protocol the overall result stays red until that global debt
is separately cleared — that is not an M017 deliverable.

## 7. Conclusion

M017 is functionally qualified against real, bounded data and a full regression:
every listed phase has reproducible evidence, the four hostile-review defects are
repaired with regression coverage, privacy holds (no addresses/PII reach logs,
the queue, or the audit trail), and the milestone adds no new static-analysis
findings. The only open items are the pre-existing repository-wide ruff/mypy
debt and the externally-blocked PST/OST dependency.
