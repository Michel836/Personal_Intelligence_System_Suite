"""Packaging contract: a wheel install must be runnable on its own."""
from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def test_core_runtime_dependencies_are_declared() -> None:
    deps = _project()["dependencies"]
    assert deps, "the wheel must declare runtime dependencies"
    names = {dep.split(">")[0].split("=")[0].split("[")[0].strip().lower() for dep in deps}
    # Canonical surfaces cannot work without these.
    for required in {
        "streamlit", "pydantic", "loguru", "numpy", "pandas",
        "pypdf2", "python-docx", "openpyxl", "odfpy", "starlette", "uvicorn",
    }:
        assert required in names, f"missing core dependency: {required}"


def test_optional_extras_cover_heavy_backends() -> None:
    extras = _project()["optional-dependencies"]
    for name in {"ai", "ocr", "docs", "dev"}:
        assert extras.get(name), f"missing optional extra: {name}"
    assert any("torch" in dep for dep in extras["ai"])
    assert any("pytest" in dep for dep in extras["dev"])


def test_pis_console_script_and_package_data() -> None:
    project = _project()
    assert project["scripts"]["pis"] == "src.cli:main"
    tool = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]
    assert tool["setuptools"]["package-data"]["src.intel"] == ["*.json"]
