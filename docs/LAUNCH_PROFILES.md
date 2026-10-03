# Launch Profiles — Operations Guide (M012-B2)

## Lite MVP update

The Lite user interface now has four workflow screens. Its backend capability
registry remains compatible with existing services; navigation is deliberately
simpler than that registry. See [LITE_MVP.md](LITE_MVP.md) for the authoritative
Lite workflow and installation dependency set. SMART/FULL keep their existing UI.

One canonical application (`src/ui/app.py`) is launched through three coherent
profiles: **LITE**, **SMART** and **FULL**. Lite now presents four workflow
screens; SMART/FULL retain the broader navigation. Profiles change defaults
(AI mode, heavyweight processing, capability exposure), with environment
overrides for backend services. This document is the current
operations reference; the historical README launch claims are reviewed at the
end.

## TL;DR — Kubuntu / Linux

```bash
scripts/run_lite.sh            # fastest, core-only, local-only AI
scripts/run_smart.sh           # hardware-aware AUTO, all capabilities lazily
scripts/run_full.sh            # every implemented capability, lazily loaded
```

Equivalent unified entrypoint (any platform):

```bash
.venv/bin/python -m src.launcher --profile lite
.venv/bin/python -m src.launcher --profile smart
.venv/bin/python -m src.launcher --profile full
```

Windows (PowerShell / cmd):

```powershell
.venv\Scripts\python.exe -m src.launcher --profile lite
```

> Do **not** use the historical `.venv/Scripts/python.exe -m streamlit run
> lite_mode.py` commands.  The `launchers/*.py` scripts are now thin
> compatibility wrappers (see [Compatibility](#compatibility)).

## Profile contracts

| Profile | Intent | Default AI mode | Exposed capabilities | Preferred port |
|---------|--------|-----------------|----------------------|----------------|
| **LITE** | Fastest startup, lowest resources, offline-capable | `local` | core only (scan, search, advanced search, tags, dashboard, statistics, viewer, archive viewer, settings) | 8510 |
| **SMART** | Hardware-aware adaptive defaults | `auto` | core + all advanced capabilities | 8504 |
| **FULL** | Every implemented mono-user capability | `auto` | core + all advanced capabilities | 8501 |

Advanced capabilities: semantic search (`🧠 AI Search`), RAG chat (`💬 AI Chat`),
advanced AI (`🤖 Advanced AI`), visualizations (`🌌 Visualizations`), cloud sync
(`☁️ Cloud Sync`) and auto-extract (`🔄 Auto-Extract`).

Core capabilities are exposed by **every** profile and cannot be disabled: search,
scan, viewer, tags, dashboard, statistics and settings always remain reachable.

### Per-profile environment defaults

These are applied **only when the operator has not set the variable**:

| Variable | LITE | SMART | FULL |
|----------|------|-------|------|
| `PIS_AI_MODE` | `local` | `auto` | `auto` |
| `PIS_REMOTE_CONTENT_POLICY` | `never` | `never` | `never` |
| `PIS_HEAVY_PRELOAD` | `0` | `0` | `0` |
| `PIS_OCR_ENABLED` | `0` | `0` | `0` |
| `PIS_ARCHIVE_PROCESSING` | `0` | `1` | `1` |
| `PIS_BACKGROUND_PROCESSING` | `0` | `1` | `1` |

`PIS_REMOTE_CONTENT_POLICY=never` is a default in **every** profile: a profile can
never widen the privacy policy on its own.

## Platform support (Linux first)

* Launch wrappers use `.venv/bin/python` on Linux/macOS (Windows uses
  `.venv\Scripts\python.exe`); the launcher itself uses `sys.executable`.
* File / folder opening is cross-platform via `src/utils/os_open.py`
  (`xdg-open` on Linux, `open` on macOS, `explorer`/`startfile` on Windows).
  No UI module hard-codes a Windows path or `explorer` command.
* No `.bat`, PowerShell-only syntax or `C:\` paths are required to launch.

## Configuration precedence

Highest priority wins:

1. **Explicit CLI / environment** — `--port`, and any `PIS_*` variable already set
   in the environment (API keys, `PIS_AI_MODE`, `PIS_EMBEDDING_BACKEND`,
   `PIS_OCR_ENABLED`, capability flags, …).
2. **Profile defaults** — only fill variables that are absent or blank.
3. **Application defaults** — built-in conservative fallbacks.

Capability flags may be toggled individually with
`PIS_FEATURE_<CAPABILITY>` (for example `PIS_FEATURE_AI_CHAT=1`,
`PIS_FEATURE_VISUALIZATIONS=0`).  Core capabilities ignore a "0" so they can
never be hidden by accident.

Inspect the resolved plan without launching anything:

```bash
.venv/bin/python -m src.launcher --profile smart --print-config
.venv/bin/python -m src.launcher --profile smart --dry-run
```

## AI mode ↔ profile interaction

| Profile | Default `PIS_AI_MODE` | Behaviour |
|---------|------------------------|-----------|
| LITE | `local` | Local-only router chain. No remote HTTP call is ever made; Ollama is optional and the app degrades to lexical/FTS search without it. |
| SMART | `auto` | Hardware-tier aware. With a remote provider configured **and** a non-`never` policy, AUTO may prefer remote; otherwise local. |
| FULL | `auto` | Same AUTO logic as SMART; embeddings stay local by default on PERFORMANCE hardware. |

Rules that hold in every profile:

* `PIS_REMOTE_CONTENT_POLICY=never` (default) ⇒ no remote provider is ever used,
  regardless of `PIS_AI_MODE`.
* An explicit `PIS_AI_MODE` / `PIS_LLM_BACKEND` / `PIS_EMBEDDING_BACKEND`
  always wins over the profile default.
* API credentials are never required; no profile raises if they are missing.
* No profile preloads an embedding/LLM model at startup.

## Module visibility

| Capability | Where surfaced | LITE | SMART | FULL |
|------------|----------------|:----:|:-----:|:----:|
| Scan / lifecycle | `🚀 Scanner` | ✅ | ✅ | ✅ |
| FTS filename/content search | `🔍 Search` | ✅ | ✅ | ✅ |
| Advanced search | `🎯 Advanced Search` | ✅ | ✅ | ✅ |
| Tags / favorites | `🏷️ Tags & Favorites` | ✅ | ✅ | ✅ |
| Dashboard / statistics | `📊 Dashboard`, `📈 Statistics` | ✅ | ✅ | ✅ |
| File / archive viewer | `👁️ File Viewer` | ✅ | ✅ | ✅ |
| Semantic search | `🧠 AI Search` | ➖ | ✅ | ✅ |
| RAG chat | `💬 AI Chat` | ➖ | ✅ | ✅ |
| Advanced AI | `🤖 Advanced AI` | ➖ | ✅ | ✅ |
| Visualizations | `🌌 Visualizations` | ➖ | ✅ | ✅ |
| Cloud sync | `☁️ Cloud Sync` | ➖ | ✅ | ✅ |
| Auto-extract | `🔄 Auto-Extract` | ➖ | ✅ | ✅ |

`➖` means hidden by default, not removed: enable with
`PIS_FEATURE_<CAPABILITY>=1`.

## Port behaviour

* Preferred ports are historical conveniences only (8510 / 8504 / 8501); nothing
  depends on them.
* If the preferred port is occupied, the launcher selects the next free port and
  reports the chosen URL.
* An **explicit** `--port` or `PIS_PORT` is respected as-is and fails loudly if
  the port is occupied (no silent relocation).
* `--host` binds an explicit address (default `127.0.0.1`).

```bash
.venv/bin/python -m src.launcher --profile lite --port 9000
PIS_PORT=9000 .venv/bin/python -m src.launcher --profile lite
```

## Lazy loading

Before M012-B2 every profile imported `torch`/`sentence-transformers` at app
startup (~1 GB RSS, ~3 s import).  Now:

* The canonical app imports heavy components (semantic search, chat engine,
  advanced AI, visualizations, auto-extractor) **on first use**, not at startup.
* The sidebar AI indicator and the AI status expander use a *cheap* provider
  probe that never constructs a local model.
* `ProviderRouter` exposes `status(cheap=True)` for diagnostics; the default
  `status()` is unchanged for callers that want constructed providers.

## Measured results (M012-B2)

Measured on this workstation: Kubuntu/Linux, Python 3.11.15, Streamlit 1.64.0,
NVIDIA RTX 3090 (24 GB), 3 runs per profile, isolated temporary database, API env
stripped, `PIS_REMOTE_CONTENT_POLICY=never`.  Reproduce with:

```bash
python scripts/bench/bench_launch_profiles.py --runs 3
```

`server boot` = process spawn → Streamlit health endpoint.  `app ready` =
clean-process cold start → canonical app first render (via Streamlit `AppTest`).

| Profile | server boot p50 | app ready p50 (min–max) | peak RSS | heavyweight AI providers loaded | VRAM delta | remote requests |
|---------|----------------:|------------------------:|---------:|:-------------------------------:|-----------:|----------------:|
| LITE | 0.36 s | 0.87 s (0.87–0.90) | 168.8 MB | none | 0 MB | 0 |
| SMART | 0.35 s | 0.88 s (0.87–0.89) | 168.1 MB | none | 0 MB | 0 |
| FULL | 0.35 s | 0.88 s (0.88–0.90) | 168.6 MB | none | 0 MB | 0 |

All three profiles have essentially the same startup cost because they all run
the same canonical app and none loads a model eagerly.  Profile differences
appear only when an advanced feature is used (for example opening `💬 AI Chat`
loads the configured provider on demand).

Notes:

* `plotly` is imported by Streamlit itself (even for LITE) and is not an AI
  provider; it accounts for part of the ~169 MB baseline.
* GPU memory is untouched at startup on all profiles (0 MB delta). The RTX 3090
  is only used when an embedding/LLM operation actually runs.

## Historical claims review

The original README advertised `.venv/Scripts/python.exe ... lite_mode.py`, ports
8510/8504/8501 as requirements, and the following figures:

| Historical claim | Classification | Current measured reality |
|------------------|----------------|--------------------------|
| LITE: startup `<1 s` | **validated** | app ready p50 0.87 s |
| LITE: `30 MB` RAM | **obsolete / needs revised documentation** | ~169 MB peak for the canonical app (Streamlit + plotly baseline); 30 MB applied to a stripped standalone script that no longer exists |
| SMART: RAM/startup "variable" | **validated** | adaptive AUTO defaults; startup ≈ 0.88 s at rest, scales with enabled features |
| FULL: startup `~25 s` | **obsolete** | app ready p50 0.88 s (lazy loading); 25 s reflected eager import/model load |
| FULL: `2.8 GB` RAM | **unrealistic as a startup figure** | ~169 MB at rest; multi-GB usage only if large local models are loaded on demand via AI features |
| Fixed ports as requirements | **obsolete technical choice** | ports are defaults with automatic free-port selection and explicit overrides |

The code was **not** tuned to hit the obsolete numbers; the modern figures are
the honest consequence of one canonical, lazily-loaded app.

## Compatibility

The historical launchers are thin compatibility wrappers:

| Historical entrypoint | Behaviour |
|-----------------------|-----------|
| `python launchers/lite_mode.py` | delegates to `src.launcher --profile lite` |
| `python launchers/smart_launcher.py` | delegates to `src.launcher --profile smart` |
| `python launchers/launcher.py` | delegates to `src.launcher --profile full` |
| `streamlit run launchers/*.py` | prints a migration message (obsolete) |

`src/ui/modern_app.py` remains available as a separate experimental UI via
`streamlit run src/ui/modern_app.py`; it is **not** part of the launch profiles.
The stale duplicate `src/ui/app_backup.py` was removed.

## Failure behaviour

| Situation | Expected behaviour |
|-----------|--------------------|
| No GPU | All profiles start; AUTO selects local/CPU providers; no crash. |
| No Ollama | LITE uses FTS; SMART/FULL degrade to lexical + `SimpleChatEngine`; the app stays usable. |
| No API / bad API config | Remote providers are skipped; no credentials required. |
| Invalid `PIS_LAUNCH_PROFILE` | App falls back to FULL; the CLI exits with a clear error. |
| Occupied port | Preferred ports auto-move; explicit ports fail loudly. |
| Missing optional dependency (e.g. OCR, archive backend, plotly) | Feature degrades with an in-UI message; core pages unaffected. |
| HuggingFace offline | Semantic search degrades to lexical; no remote calls. |
| Missing file opener (`xdg-open`) | Open/reveal buttons report failure; the app and viewer keep working. |
| Read-only data dir | Core read/search still work; writes surface an error instead of crashing. |
