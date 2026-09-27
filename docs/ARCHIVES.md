# Archive & Container Support (M009J)

Archives are indexed as **searchable containers**. Each member becomes a
*virtual document* row in the canonical `files` table, so lexical (FTS),
semantic and lifecycle machinery are reused without duplicating extraction
logic. Member paths are never treated as real filesystem paths and members are
never extracted back into a source directory.

## Supported formats

| Format | Backend | Notes |
|---|---|---|
| ZIP | `zipfile` (stdlib) | Unicode names, duplicates, nested, encrypted detection |
| TAR / TAR.GZ / TGZ / TAR.BZ2 | `tarfile` (stdlib) | symlinks/hardlinks/devices are metadata-only |
| TAR.XZ / XZ | stdlib `lzma` or the `7z` CLI | falls back to `7z` when `_lzma` is unavailable |
| GZ / BZ2 | `gzip` / `bz2` (stdlib) | exposed as a single decompressed member |
| 7Z | `py7zr`, else the `7z` CLI | empty-password archives are distinguished from locked ones |
| RAR | `rarfile` + `unrar`/`unar`/`bsdtar`/`7z` | `BACKEND_UNAVAILABLE` when no tool exists |

A missing backend or a corrupt/locked archive returns an explicit status and
never raises out of the batch.

## Bounded member extraction (M013-C2)

Listing has its own deadline (`PIS_ARCHIVE_TIMEOUT`). Member extraction is
additionally bounded by a per-archive total budget
(`PIS_ARCHIVE_EXTRACT_TIMEOUT`, default 120 s). When the budget is exhausted the
archive returns the transient `LIMIT_EXTRACT_TIME` status, the members already
extracted stay valid, and the remaining members stay `PENDING`. Because
`LIMIT_EXTRACT_TIME` is not a deterministic status it is never cached, so a
later run resumes the archive and processes only its `PENDING` members (terminal
member states are skipped). The budget is checked between members, so the
overshoot is at most one member; a single archive can never monopolise the
pipeline.

## Virtual member identity

```
/home/chu/Documents/backup.zip!/reports/quarterly.pdf
```

Persisted per member: `parent_archive_id`, `archive_member_path`,
`archive_depth`, `archive_format`, `member_type`,
`member_compressed_size`, `member_uncompressed_size`, `member_crc`,
`member_encrypted`, `member_state` (ACTIVE/MISSING), `extraction_state`.
The parent row keeps `archive_fingerprint`, `archive_indexed_at`,
`archive_processing_version`, `archive_status`, `archive_member_count`,
`archive_encrypted_count`, `archive_compressed_size`, `archive_expanded_size`.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `PIS_ARCHIVE_ENABLED` | `1` | master switch |
| `PIS_ARCHIVE_POLICY` | `SAFE_SUPPORTED_MEMBERS` | `METADATA_ONLY` / `SAFE_SUPPORTED_MEMBERS` / `FULL_WITHIN_LIMITS` |
| `PIS_ARCHIVE_MAX_DEPTH` | `3` | nested-archive recursion depth |
| `PIS_ARCHIVE_MAX_MEMBERS` | `5000` | cumulative member-count budget |
| `PIS_ARCHIVE_MAX_MEMBER_BYTES` | `67108864` | per-member decompressed cap |
| `PIS_ARCHIVE_MAX_TOTAL_UNCOMPRESSED` | `1073741824` | cumulative decompressed cap |
| `PIS_ARCHIVE_MAX_RATIO` | `200` | compression-ratio guard (files > 1 MiB) |
| `PIS_ARCHIVE_TIMEOUT` | `30` | per-archive **listing/indexing** deadline (seconds) |
| `PIS_ARCHIVE_EXTRACT_TIMEOUT` | `120` | per-archive **member-extraction** budget (seconds) |

## Safety

- **Path traversal**: absolute, UNC, Windows drive/drive-relative, `..` and NUL
  members are rejected; backslash names are normalised; nothing is written
  outside the virtual namespace.
- **Decompression bombs**: declared metadata limits *and* streaming byte limits
  are enforced, so lying headers cannot exhaust memory; nested archives share a
  cumulative budget.
- **Links**: symlinks/hardlinks/device entries are metadata-only and never
  followed.
- **Temp files**: bounded materialization happens in a per-archive
  `TemporaryDirectory` that is always cleaned up.
- **Timeouts / subprocesses**: the 7z CLI always runs with `-p-`/`-y` and a
  hard timeout, so no password prompt can block indexing.
- **No bulk extraction**; extraction reuses the existing `ExtractionManager`
  and only text is stored (binary archive payloads are never embedded).

## Reprocessing

The parent fingerprint (`size:mtime`, optional content hash) plus
`archive_processing_version` skip unchanged archives across scans. A changed
archive reconciles members by path/CRC: unchanged members keep their identity
and content, new members become ACTIVE, removed members become MISSING (never
deleted) and changed members are reset for re-extraction. When a parent archive
disappears its members are marked MISSING so no stale ACTIVE virtual document
remains.
