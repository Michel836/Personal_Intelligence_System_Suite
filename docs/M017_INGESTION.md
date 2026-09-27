# Email, Legacy Formats, OCR Hardening & Error Queue (M017)

M017 improves real-world ingestion coverage and reliability. It is **local-only**:
no cloud conversion, no destructive source modification, no mandatory external
service, no multi-user workflow.

New package: `src/ingest/` (`taxonomy.py`, `queue_store.py`, `pipeline.py`,
`capabilities.py`, `cfb.py`, `thread_store.py`, `tools.py`). New extractors:
`email_extractor.py`, `legacy_extractor.py`, `epub_extractor.py`,
`chm_extractor.py`, all wired into the canonical `ExtractionManager`. Hardened
`ocr.py`. UI page: **🛠️ Ingestion & Coverage** (capability `ingestion`).

## Format capability matrix

| Format | Status | Path |
|---|---|---|
| PDF | SUPPORTED | `pdf_extractor` |
| Office modern (docx/xlsx/pptx) | SUPPORTED | `office_extractor` |
| Office legacy (doc/xls/ppt) | PARTIAL | `legacy_extractor` (antiword/catdoc/xls2csv/catppt/LibreOffice) |
| RTF | PARTIAL | `legacy_extractor` (unrtf/LibreOffice) |
| WordPerfect (wpd/wps) | **DEFERRED** | LibreOffice if present — **0 files in the M013 corpus** |
| OpenDocument (odt/ods/odp) | SUPPORTED | `odf_extractor` |
| Email EML / MHT | SUPPORTED | `email_extractor` (stdlib) |
| Email MSG | PARTIAL | `email_extractor` (native bounded CFB reader) |
| PST/OST | **UNSUPPORTED (dependency)** | needs `readpst`/libpff or `pypff` (absent) |
| MBOX | DEFERRED | 0 files in the corpus |
| EPUB | SUPPORTED | `epub_extractor` (stdlib zip+HTML) |
| CHM | PARTIAL | `chm_extractor` (local 7z, temp space) |
| OCR (images / scanned PDF) | PARTIAL (opt-in) | `ocr.py` (pytesseract, eng/deu/fra/osd) |
| Archives | PARTIAL | `archives/` (RAR needs unrar/unar/7z) |

The capability matrix is generated live and reports the exact missing tools.

## Email semantics

For each message: subject, sender/recipients, date, plain-text body, HTML body
normalised to text, attachment **metadata** (name/type/size — never executed),
`Message-ID`, `In-Reply-To`, `References`, and nested `message/rfc822` (bounded).
Extracted text is stored through `db.update_content`, so it is searchable like
any other document. Addresses are never logged.

* **EML/MHT**: stdlib `email` with `policy.default` (malformed-MIME tolerant),
  charset decoding, multipart, HTML fallback, attachment metadata, nested depth ≤ 2.
* **MSG**: stdlib-only bounded OLE/CFB reader extracting the `__substg1.0_*`
  property streams (subject/body/sender/recipients/date). Gracefully reports
  `MALFORMED` for corrupt files. `extract_msg`/`pypff` would add fidelity if installed.
* **PST/OST**: no local reader is available; reported as `UNSUPPORTED_DEPENDENCY`
  with the exact requirement (`readpst` from `libpff-tools`, or the `pypff`
  Python package). **No fake PST support.**

## Email threading

`email_threads` stores thread relations derived **only from RFC headers**
(`Message-ID`/`In-Reply-To`/`References`), never from subject text. The M016
`RelationService` exposes them as the directed `EMAIL_REPLY_TO` relation with
header evidence.

## Legacy extraction strategy

Layered, bounded, temp-space only:
1. installed filter tool (antiword / catdoc / xls2csv / catppt / unrtf),
2. headless LibreOffice conversion,
3. explicit `UNSUPPORTED_DEPENDENCY`.

All runs use `subprocess` **without a shell**, a hard timeout, bounded output,
and temp copies with guaranteed cleanup. Source files are never modified.

## OCR policy & hardening

* **Candidates only**: image-only PDFs (extraction produced no text) and images
  explicitly requested. Ordinary photos are not OCR'd by default.
* Installed languages are **detected** (`tesseract --list-langs`) and the
  requested set is intersected with them (graceful fallback, never a crash).
* Grayscale + autocontrast preprocessing and Tesseract OSD orientation
  correction when the `osd` model is present.
* Bounded by file size, page count and per-page timeout; empty/low-confidence
  output is `OCR_FAILED`/`NO_TEXT`, not a crash.

## Extraction outcome taxonomy

`EXTRACTED`, `NO_TEXT`, `UNSUPPORTED_FORMAT`, `UNSUPPORTED_DEPENDENCY`,
`MALFORMED`, `ENCRYPTED`, `PASSWORD_REQUIRED`, `TIMEOUT`, `RESOURCE_LIMIT`,
`OCR_REQUIRED`, `OCR_FAILED`, `TRANSIENT_ERROR`, `PERMANENT_ERROR`.
Archive-specific statuses remain compatible.

## Error queue & retry policy

`extraction_queue` stores file id, operation, outcome, a short non-sensitive
detail, attempt count, first/last timestamps, `retry_after`, terminal flag and
extractor version. Retryable: `TIMEOUT`, `TRANSIENT_ERROR`,
`UNSUPPORTED_DEPENDENCY` (dependency may appear), `OCR_FAILED` — bounded to 3
attempts with exponential backoff (60s/300s/1500s, cap 1h). Terminal:
`NO_TEXT`, `UNSUPPORTED_FORMAT`, `MALFORMED`, `ENCRYPTED`,
`PASSWORD_REQUIRED`, `RESOURCE_LIMIT`, `PERMANENT_ERROR`. No infinite retries;
missing files are pruned.

`OCR_REQUIRED` is deliberately **neither** auto-retried **nor** terminal: it
stays visible in the issue list and is retried explicitly (UI *Retry now*, or
by enabling `PIS_OCR_ENABLED`) so a disabled OCR stack never causes a retry
storm.

## Recovery / resume

Every outcome is committed per file; a killed process resumes from the queue and
re-selects only unprocessed/retryable rows. Already-successful documents are not
reprocessed (`content_extracted=1`). Temp conversion directories are per-run and
cleaned automatically.

## Privacy

Email/PST data is highly sensitive: processing is local, temp outputs are
cleaned, PII masking and the M012 remote policy remain authoritative, the audit
trail records actions without payloads, and no raw addresses are logged.

## Measured (M013-C corpus copy, real files)

| Format | Tested | Result | Wall |
|---|---:|---|---:|
| MSG (native CFB) | 192 | **192 EXTRACTED** | 1.95 s |
| EML | 3 | 3 EXTRACTED | 0.08 s |
| DOC | 6 | 6 EXTRACTED | 0.05 s |
| XLS | 12 | 8 EXTRACTED · 4 NO_TEXT | 1.13 s |
| RTF | 6 | 6 EXTRACTED | 10.2 s |
| CHM | 42 | 42 EXTRACTED | 12.1 s |
| EPUB | 200 | 200 EXTRACTED | 11.7 s |
| OCR (image-only PDFs) | 10 | 10 EXTRACTED | ~25 s/page-ish |
| Peak RSS | — | ~500 MB | — |


## Extraction quality (M013-C corpus copy + synthetic fixtures)

From `scripts/bench/m017_quality.py` (aggregate only; no path or filename is
recorded). Synthetic fixtures carry a known token per format and must not leak
attachment payloads; the real sample is a small **read-only** slice per
extension from the validated trial DB.

| Probe | Result |
|---|---|
| EML plain / HTML / nested / attachment token recall | 1.0 · attachment payload not leaked |
| MSG (native CFB) token recall | 1.0 |
| EPUB / RTF token recall | 1.0 |
| OCR character similarity (3 synthetic images, eng/deu/fra) | mean **0.981** |

Real bounded sample (success / tested, mean printable ratio):

| Format | Tested | Success | Non-empty | Mean chars | Printable |
|---|---:|---:|---:|---:|---:|
| MSG | 20 | 20 | 20 | 5,866 | 0.975 |
| EML | 3 | 3 | 3 | 1,538 | 0.991 |
| DOC | 6 | 6 | 6 | 11,333 | 0.998 |
| XLS | 12 | 8 | 8 | — | 1.000 |
| RTF | 6 | 6 | 6 | 38,950 | 1.000 |
| CHM | 20 | 20 | 20 | 645,121 | 1.000 |
| EPUB | 20 | 20 | 20 | 802,788 | 0.999 |

## Hostile review (M017)

Adversarial pass on the new code found and repaired:

1. **Duplicate attachment metadata** — `msg.walk()` *and* a manual recursion
traversed every part, recording each attachment twice. Fixed to a single
traversal (regression: `test_eml_plain_html_multipart_and_attachment`).
2. **Dropped nested `message/rfc822` body** — only the first text part was kept.
Bodies are now assembled per MIME depth, so an inner message is preserved
(bounded by `MAX_NESTED_DEPTH`).
3. **Silent `OCR_REQUIRED` retry storm** — a non-terminal, non-retryable outcome
received a `NULL` backoff and was swept into every automatic retry. The retry
selector now honours the documented retryable set only.
4. **Bounded reads** — EPUB entries are size-checked before being read, CHM
extraction is rejected past an on-disk cap, and the LibreOffice text output is
read with a hard byte limit.

Residual (documented, not hidden): PST/OST remain `UNSUPPORTED (dependency)`
because neither `readpst`/`libpff` nor `pypff` is installed; a CHM/zip bomb is
bounded by the 90 s timeout and the post-extraction size cap rather than by an
up-front archive header check.

Corpus prevalence (M013-B): `.msg` 192, `.eml` 3, `.doc` 6, `.xls` 12, `.rtf` 6,
`.chm` 42, `.epub` 554, `.tif` 4, `.pdf` 4,209 (≈1,412 image-only), `.wpd` 0,
`.pst` 0.
