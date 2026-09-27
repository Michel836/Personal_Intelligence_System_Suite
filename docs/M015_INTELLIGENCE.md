# Document Intelligence & Local Privacy (M015)

M015 adds a **local-only** document-understanding layer on top of the canonical
stack: language detection, named entities, configurable categorisation, PII
classification, privacy-aware search, a non-destructive redaction preview and a
local audit trail.

New package: `src/intel/` (`store.py`, `language.py`, `entities.py`,
`categories.py`, `pii.py`, `pipeline.py`, `search.py`, `relationships.py`,
`redact.py`, `audit.py`, `privacy.py`, `taxonomy.json`). New canonical tables:
`doc_language`, `doc_entities`, `doc_categories`, `doc_pii`,
`category_overrides`, `doc_intel_state`, `audit_events`, `privacy_meta`.
UI page: **🧠 Document Intelligence** (core capability `intelligence`).

**No accounts, RBAC, multi-user auth, cloud telemetry or mandatory external
APIs. No private corpus content leaves the machine. No destructive action.**

## Language detection

* Dependency-free: unicode script ranges + language-specific diacritics +
  high-frequency stopword profiles (FR/DE/EN priority, plus ES/IT/PT/NL and
  script-based RU/AR/ZH/JA/EL/HE/HI).
* States: `OK`, `UNKNOWN`, `INSUFFICIENT_TEXT` (< 8 tokens), `CODE`.
* Confidence in `[0,1]`; `mixed` lists co-occurring languages when evidence
  permits. Input is capped so a huge document cannot distort detection.
* Detection runs on extracted text (physical files and archive members).

## Named entities

| Type | Method | Reliability |
|---|---|---|
| EMAIL, URL, PHONE, IP, IBAN, CARD | regex + validation | high |
| DATE, MONEY | regex | medium/high |
| PERSON, ORGANIZATION, LOCATION | title prefix / legal suffix / small gazetteer | **low (heuristic)** |

Unreliable classes are explicitly marked `method="…_heuristic"` and low
confidence; they are never presented as certain. Records store type, normalized
value (fingerprint for PII-typed entities), masked display, count, confidence
and extractor version.

## Categorisation

* **Structural** categories from extension/type (document_pdf, spreadsheet,
  source_code, archive, image, …).
* **Topic** categories from a configurable JSON taxonomy
  (`src/intel/taxonomy.json`) using keyword matching; an optional semantic
  similarity against category descriptions can use the existing embedding store
  (no per-document LLM call).
* Multi-label with score + source; `UNKNOWN` when nothing matches.
* **Manual user overrides always win** (`category_overrides`), including
  negative overrides.

## PII definitions & limitations

Conservative, validation-first:
* `email`, `phone` (8–15 digits), `postal_address` (street/PLZ patterns),
  `person_name` (title heuristic), `ip` (parsed), `date_of_birth` (contextual).
* `iban` (**mod-97**), `card` (**Luhn**), `national_id` (FR **NIR** key),
  `account_id` (context + ≥2 digits).
* A numeric string is **never** PII without validation/context.

Findings store **type, severity, count, confidence, detector, version, a salted
fingerprint and a masked display only** — never the raw value. Masking examples:
`j***@example.com`, `FR76 **** **** 0189`, `**** **** **** 1111`, `192.168.*.*`.
The salt lives in `privacy_meta` and is used for correlation/identity, not
secrecy. Raw values are never logged.

## Privacy-aware search

`DatabaseManager.search_files(...)` gained optional filters `language`,
`category`, `has_pii`, `exclude_high_sensitivity`, `entity_type`,
`entity_value`. They compile to `EXISTS` subqueries and are **absent by
default**, so canonical FTS/LIKE behaviour and M014 reranking are unchanged.

## Redaction preview

`redacted_preview(text)` returns a masked copy for display. It re-reads the
stored extracted text, never writes to the source file, and does not persist the
unmasked text. Export of a redacted derivative is deliberately **not** enabled
in this lot.

## Encryption / protection boundary

`cryptography` is **not installed** in this environment. The useful protection
for this mono-user app is therefore:
* keep secrets in the environment / `.env` (never in the DB or logs) — already
  the case for API keys;
* rely on **OS-level full-disk encryption** for the home volume (the correct
  boundary for source files, the SQLite DB, extracted text and the embedding
  store);
* do **not** add application-level encryption with a key stored beside the
  ciphertext, which would be pointless and would break FTS/semantic search.

This lot documents that boundary rather than pretending "encryption" exists.

## Local audit trail

`audit_events` records `sensitive_document_viewed`, `pii_filter_search`,
`redacted_preview`, `category_override`,
`remote_content_policy_changed`, `intel_pipeline_run`, … with timestamp,
target, a short non-sensitive detail and sensitivity class. It is bounded
(`prune(keep=10000)`) and mirrors to the loguru `audit` stream. It never records
document content, PII values, queries that may contain PII or API keys.

## Remote / AI-router interaction

The M012 `RemoteContentPolicy` remains **authoritative**. PII metadata can only
*warn* when the user has explicitly enabled remote sending; it never relaxes,
overrides or auto-changes the policy. `remote_warning(policy, findings)` returns
`None` under `never`/`metadata_only`.

## Incremental freshness

`doc_intel_state` records the source `indexed_at` and content length. A document
is reprocessed only when it is new or its content changed; deletions prune all
intel metadata. Archive members are first-class. NLP text is capped
(`MAX_NLP_CHARS=100 000`) so a pathological document cannot monopolise a run.

## Measured (M013-C corpus copy, bounded sample)

| Metric | Value |
|---|---|
| Documents analysed | 3,000 (55k+ in the full staged run) |
| Throughput | **36.4 docs/s** (local, no LLM) |
| No-change re-processing | **0 documents** (stale-check ~2.6 s) |
| DB growth | ~5.1 MB / 3,000 docs (~1.7 KB/doc) |
| Filtered search (language/PII) | p50 **38 ms** |
| Language mix (sample) | code 2047, en 573, fr 327, de 24, es 9, it 8, pt 6, und 6 |
| PII (corrected conservative detectors) | phone 1,075 · address 954 · email 656 · name 307 · ip 148 · iban 11 · card 7 |
| Entity types | URL 6,514 · DATE 4,574 · MONEY 3,777 · ORG 2,088 · PHONE 1,075 · LOC 984 · EMAIL 656 · PERSON 307 |

The initial permissive phone/card detectors produced ~121k/14k false-positive-heavy findings; they were replaced with format-aware phone detection and issuer/Luhn card validation, cutting phone findings ~8× per document and cards to a handful. `filtered search` that does not narrow the row set inherits the pre-existing ~1 s filter-only ORDER BY cost; selective filters (language/category/PII) are milliseconds.

## False-positive limitations

Language detection can be uncertain on short/ambiguous text (returns
`UNKNOWN`/`INSUFFICIENT_TEXT` rather than guessing). PERSON/ORG/LOCATION are
heuristic. Phone/address/account detectors are deliberately conservative and
biased toward false negatives. A "shared entity" view means *the entity occurs
in both documents*, not that any real-world relationship exists.
