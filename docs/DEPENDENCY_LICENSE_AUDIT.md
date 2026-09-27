# Dependency License Audit — Personal Intelligence System Suite

Status: release-candidate licensing review for the `AGPL-3.0-only` + separate commercial-license model.

This document is an engineering inventory, not legal advice. Upstream license texts remain authoritative. Re-run the audit before commercial redistribution, after dependency upgrades, and whenever a component becomes bundled instead of merely invoked externally.

## Executive conclusion

No declared direct Python dependency reviewed here has been identified as preventing the project's own original code from being offered under `AGPL-3.0-only`.

A separate commercial license for project-owned code is also structurally possible, but it **cannot relicense third-party packages, model weights, external executables, datasets, or services**. Commercial packaging must preserve the obligations of every bundled third-party component.

Important packaging flags:

- `psycopg` is LGPL-3.0-only; using the library is compatible with the AGPL project, but the LGPL terms remain applicable to psycopg itself.
- `opencv-python` wheels may bundle FFmpeg under LGPL and non-headless Linux wheels may bundle Qt 5 under LGPLv3; redistribution must preserve those notices/terms.
- external tools such as Ghostscript, Poppler, Pandoc, LibreOffice, 7-Zip/unrar, Chrome/Chromium and Tesseract have their own licenses and are not relicensed by PISS.
- Redis **client** (`redis-py`) is MIT; a Redis **server** has version-dependent licensing and must be audited separately if distributed.
- AI model licenses are separate from the Ollama client/runtime license and must be reviewed model by model.

## Relationship classes

- **Library** — imported by project code.
- **External executable/service** — invoked or contacted but not part of project copyright.
- **Optional backend** — deployment-specific component.
- **Model/data** — independently licensed content or weights.

## Declared Python/runtime dependencies

The table is based on the repository's declared requirements and upstream/PyPI license metadata available during this review.

| Component | Relationship | License / status | AGPL project compatibility | Commercial distribution note |
|---|---|---|---|---|
| FastAPI | Library | MIT | Compatible | Preserve upstream notices if redistributed |
| Uvicorn | Library | BSD-3-Clause | Compatible | Preserve notices |
| Streamlit | Library | Apache-2.0 | Compatible | Preserve Apache notices/license |
| Pydantic | Library | MIT | Compatible | Preserve notices |
| python-dotenv | Library | BSD-3-Clause | Compatible | Preserve notices |
| Loguru | Library | MIT | Compatible | Preserve notices |
| psycopg 3 | Library | LGPL-3.0-only | Compatible as separate library | LGPL obligations remain for the library; do not represent it as commercially relicensed |
| asyncpg | Library | Apache-2.0 | Compatible | Preserve Apache notices/license |
| Alembic | Library | MIT | Compatible | Preserve notices |
| pgvector-python | Optional library | MIT | Compatible | PostgreSQL server/extensions have separate terms |
| redis-py | Library/client | MIT | Compatible | Redis server licensing is version-dependent and separate |
| MinIO Python SDK | Library/client | Apache-2.0 | Compatible | MinIO server/product licensing is separate |
| Ollama Python client | Library/client | MIT | Compatible | Ollama runtime and each model/weight require separate review |
| sentence-transformers | Library | Apache-2.0 | Compatible | Models loaded through it keep their own licenses |
| PyTorch | Library | BSD/Apache/MIT family with bundled third-party notices | Compatible | Ship upstream third-party notices if bundled |
| Transformers | Library | Apache-2.0 | Compatible | Model licenses are separate |
| Accelerate | Library | Apache-2.0 | Compatible | Preserve notices |
| spaCy | Library | MIT | Compatible | Language/model packages can have separate metadata/licenses |
| NLTK | Library | Apache-2.0 | Compatible | Corpora/resources may have separate licenses |
| langdetect | Library | Apache-2.0 | Compatible | Preserve notices |
| pytesseract | Library wrapper | Apache-2.0 | Compatible | Tesseract executable separately licensed |
| EasyOCR | Library | Apache-2.0 | Compatible | Downloaded recognition models require separate model review |
| pdf2image | Library wrapper | MIT | Compatible | Poppler executable/library is separate |
| PyPDF2 | Library | BSD-style | Compatible | Preserve notices |
| python-docx | Library | MIT | Compatible | Preserve notices |
| openpyxl | Library | MIT | Compatible | Preserve notices |
| Pillow | Library | HPND-style / Pillow license | Compatible | Preserve upstream license |
| opencv-python | Library/wheel | package scripts MIT; OpenCV Apache-2.0; wheels include third-party notices | Compatible | Review bundled FFmpeg/Qt obligations before redistribution |
| pandas | Library | BSD-3-Clause | Compatible | Preserve notices |
| NumPy | Library | BSD-3-Clause | Compatible | Preserve notices and bundled component notices |
| scikit-learn | Library | BSD-3-Clause | Compatible | Preserve notices |
| faiss-cpu | Library | MIT | Compatible | Preserve notices |
| hdbscan | Optional library | BSD-style | Compatible | Preserve notices |
| Plotly Python | Library | MIT | Compatible | Plotly.js/assets retain upstream notices if bundled |
| NetworkX | Library | BSD-3-Clause | Compatible | Preserve notices |
| Celery | Library | BSD-3-Clause | Compatible | Preserve notices |
| `asyncio` PyPI backport | Library/legacy declaration | REVIEW | Avoid packaging on modern Python unless actually required; stdlib asyncio is not this package |
| cryptography | Library | Apache-2.0 / BSD-3-Clause dual licensing | Compatible | Preserve applicable notices |
| passlib | Library | BSD-style | Compatible | Preserve notices |
| python-multipart | Library | Apache-2.0 | Compatible | Preserve notices |
| tqdm | Library | MPL-2.0 / MIT licensing terms upstream | Compatible | File-level/MPL obligations remain for upstream code if bundled/modified |
| Click | Library | BSD-3-Clause | Compatible | Preserve notices |
| Rich | Library | MIT | Compatible | Preserve notices |
| cachetools | Library | MIT | Compatible | Preserve notices |
| pydantic-settings | Library | MIT | Compatible | Preserve notices |
| pytest / pytest-asyncio / pytest-cov | Development | MIT-family | Compatible | Development-only |
| Black | Development | MIT | Compatible | Development-only |
| Ruff | Development | MIT | Compatible | Development-only |
| mypy | Development | MIT | Compatible | Development-only |
| pre-commit | Development | MIT | Compatible | Development-only |

## External executables and platform components

These are **not covered by the project's AGPL grant** merely because PISS can call them.

| Component | Typical relationship | License / legal note | Distribution implication |
|---|---|---|---|
| Tesseract OCR | External executable | Apache-2.0 | Generally permissive; include license if bundled |
| Poppler tools | External executable/library | GPL family; exact build/version must be checked | Do not bundle into proprietary package without explicit compatibility review |
| Ghostscript | External executable | AGPL/commercial licensing model upstream | If bundled commercially, review Artifex licensing; system-installed invocation is a different distribution posture |
| LibreOffice | External executable | MPL-2.0 (with additional component licenses) | Preserve upstream terms/notices if bundled |
| Pandoc | External executable | GPL-2.0-or-later | Treat as separate executable; bundling needs copyleft review |
| 7-Zip | External executable | LGPL-2.1-or-later plus component-specific restrictions | Preserve licenses; unRAR-derived code has additional restrictions |
| unrar / RAR tools | External executable | proprietary/freeware terms vary | Commercial redistribution requires explicit upstream review |
| Google Chrome | External executable | proprietary Google terms plus open-source components | Do not redistribute as though covered by project license |
| Chromium | External executable | BSD-style core plus many third-party licenses | If bundled, preserve Chromium notices |
| Ollama runtime | External service/runtime | upstream software license; models separate | Audit runtime version and every model before redistribution |
| PostgreSQL | Optional external DB | PostgreSQL License | Compatible; preserve notices if bundled |
| Redis server | Optional external service | **version-dependent** (BSD <=7.2; later Redis licensing changed, with AGPL option in newer releases) | Pin and audit actual server version before commercial distribution |
| MinIO server | Optional external service | separate upstream server licensing | Audit actual server/product terms if shipped |

## AI model and data boundary

PISS can use local or remote models. The project license does not grant rights in those models.

For every release/deployment, record at minimum:

1. model identifier and exact version/digest;
2. model provider/source;
3. model license or terms of use;
4. commercial-use permission;
5. redistribution permission (if weights are shipped);
6. attribution/notice requirements;
7. acceptable-use restrictions, if any.

Do not infer a model's license from the fact that it runs through Ollama, Transformers, sentence-transformers, or another permissively licensed client.

## Hosted APIs and services

Anthropic/OpenAI-compatible providers, cloud storage, hosted databases and similar services are contractual services rather than code relicensed by this repository. Their API terms, privacy terms, data-processing provisions and usage policies remain independent.

## Vendored/copied-code rule

The current licensing strategy assumes third-party packages are dependencies, not copied into the project's source tree. Any future vendored/copied code must be audited file-by-file and retain required copyright/license notices.

## Commercial dual-license rule

A commercial customer can receive alternative terms only for material for which the commercial licensor owns or controls sufficient rights. Third-party components remain under their original licenses even when delivered alongside commercially licensed PISS code.

## Release gate

Before a commercial binary/container/installer release:

- generate a lock/SBOM from the exact build;
- enumerate transitive dependencies and bundled native libraries;
- collect required license/NOTICE files into the distribution;
- review model licenses/digests;
- review container base-image licenses and packages;
- verify no `UNKNOWN`, non-commercial, source-available-only, SSPL/RSAL, Commons-Clause, or proprietary component is unintentionally redistributed;
- obtain legal review for the actual commercial distribution form if material revenue or customer indemnities are involved.

## Sources used for this engineering review

Representative authoritative/upstream metadata checked during the review include PyPI/upstream license records for FastAPI, Pydantic, psycopg, asyncpg, Alembic, pgvector, sentence-transformers, Transformers, PyTorch, Redis Python client, Ollama, spaCy, pdf2image, openpyxl, pandas and opencv-python. Upstream license texts—not this summary—control in case of conflict.
