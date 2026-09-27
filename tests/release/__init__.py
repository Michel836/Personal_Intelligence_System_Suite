"""Canonical release acceptance suite (M021).

Deterministic, isolated and non-private. Builds a small synthetic corpus in a
temp directory, drives the canonical services/UI/CLI/API end-to-end, and checks
the release gates: source safety, privacy, backup/restore and restart.
"""
