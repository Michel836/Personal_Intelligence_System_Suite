# Validation Protocol

This repository uses a fail-closed validation workflow derived from the process used on Trajectory-OS and YT Knowledge Copilot.

## Core rules

1. Audit before repair. Do not change production behavior merely to make a gate green.
2. Work on an isolated feature/audit branch. Keep `main` untouched until evidence is reviewed.
3. Use the canonical project virtual environment when available: `./.venv/bin/python`.
4. Persist evidence for every validation run under `.validation/<UTC timestamp>/`.
5. A validation result is bound to the complete validated repository state recorded in `validation.json`: `branch`, `head`, `base_main`, `tree_state` (`CLEAN`/`DIRTY`), `committed_patch_sha256` (committed delta vs `main`), `working_tree_sha256` (content manifest of tracked and untracked non-ignored files) and `validated_state_sha256` (deterministic combination of the above). The fingerprint covers **staged, unstaged and untracked relevant changes**, not only committed work. Ignored paths (`.git/`, `.venv/`, `.validation/`, caches, bytecode, runtime data) never contribute.
6. Any repair invalidates stale evidence. Re-run validation after every material code change.
7. No validation harness command may crawl or index real user data volumes. Functional filesystem scans are a later, explicit test phase using controlled fixtures first.
8. Do not silently ignore failures. A failed gate keeps the overall validation red.

## Baseline commands

```bash
python scripts/audit_repo.py
python scripts/run_validation.py
bash scripts/quality.sh
```

`run_validation.py` records stdout and stderr for each gate independently and writes both `validation.json` and `validation.txt`. It fingerprints the repository state before the gates run and re-computes it afterwards: `state_stable_during_gates` records whether any gate mutated the validated state, and `post_validation_state_sha256` records the result of that check.

## Current baseline gates

- repository static audit and declared-entrypoint verification;
- Python bytecode compilation (`compileall`);
- Ruff;
- mypy;
- pytest;
- `git diff --check`.

These gates establish code health. They do **not** claim that every product function works.

## Functional qualification phase

Once the baseline is stable, every user-facing capability must be represented in a functional matrix and exercised in normal and adversarial states, including where relevant:

- empty state;
- nominal execution;
- invalid input and unavailable paths;
- permission errors;
- cancellation/pause/resume;
- concurrency and database locking;
- restart/recovery;
- incremental update;
- rename/move/delete detection;
- duplicate handling;
- large-file metadata handling;
- extraction failures;
- lexical, semantic and hybrid retrieval;
- unavailable LLM/embedding providers;
- UI-to-backend integration.

For each function the evidence chain is: detection -> reproducible failure -> bounded repair -> targeted regression -> full validation -> fresh evidence.

## Review gate

A change is not ready to merge merely because tests pass. Review findings are classified as blocker / major / minor / rebutted / ambiguous. Any repair requires a fresh `validated_state_sha256` and fresh validation evidence. Evidence whose `validated_state_sha256` does not match the repository state being reviewed is stale and must not be reused, even if the branch and HEAD are unchanged.

## Safety for the 36TB use case

Repository validation and fixture testing must precede any scan of large personal volumes. Real-volume tests should start with a small dedicated directory, then a bounded subset, then one volume, and only later expand to the full corpus after correctness, database integrity and recovery behavior are proven.
