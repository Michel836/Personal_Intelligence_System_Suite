"""Unified launcher: profiles, ports, precedence and compatibility (M012-B2)."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

import src.launcher as launcher
from src.core.launch_profile import LaunchProfile
from src.launcher import (
    CANONICAL_APP,
    build_child_env,
    build_plan,
    find_free_port,
    main,
    port_available,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _occupy() -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock, int(sock.getsockname()[1])


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_canonical_app_exists_and_is_the_target() -> None:
    assert (REPO_ROOT / CANONICAL_APP).is_file()
    plan = build_plan(LaunchProfile.LITE, port=_free_port(), base_env={})
    assert plan.app_path == (REPO_ROOT / CANONICAL_APP).resolve()


def test_child_env_defaults_and_precedence() -> None:
    env = build_child_env(
        LaunchProfile.LITE,
        port=8600,
        base_env={"PIS_AI_MODE": "hybrid", "CUSTOM": "keep"},
    )
    assert env["PIS_AI_MODE"] == "hybrid"  # explicit wins
    assert env["PIS_REMOTE_CONTENT_POLICY"] == "never"
    assert env["PIS_LAUNCH_PROFILE"] == "lite"
    assert env["PIS_PORT"] == "8600"
    assert env["CUSTOM"] == "keep"


def test_explicit_port_is_honoured() -> None:
    port = _free_port()
    plan = build_plan(LaunchProfile.SMART, port=port, base_env={})
    assert plan.port == port and plan.explicit_port is True


def test_env_port_is_honoured() -> None:
    port = _free_port()
    plan = build_plan(LaunchProfile.FULL, base_env={"PIS_PORT": str(port)})
    assert plan.port == port and plan.explicit_port is True


def test_occupied_explicit_port_fails_loudly() -> None:
    sock, port = _occupy()
    try:
        with pytest.raises(RuntimeError):
            build_plan(LaunchProfile.LITE, port=port, base_env={})
    finally:
        sock.close()


def test_preferred_port_moves_when_occupied(monkeypatch) -> None:
    sock, busy = _occupy()
    try:
        monkeypatch.setitem(launcher.PREFERRED_PORTS, LaunchProfile.LITE, busy)
        plan = build_plan(LaunchProfile.LITE, base_env={})
        assert plan.port != busy
        assert plan.explicit_port is False
    finally:
        sock.close()


def test_port_helpers() -> None:
    sock, port = _occupy()
    try:
        assert not port_available("127.0.0.1", port)
        with pytest.raises(RuntimeError):
            find_free_port("127.0.0.1", port, limit=1)
    finally:
        sock.close()
    free = _free_port()
    assert port_available("127.0.0.1", free)
    assert find_free_port("127.0.0.1", free) == free


def test_cli_dry_run_prints_streamlit_command(capsys) -> None:
    port = _free_port()
    code = main(["--profile", "lite", "--port", str(port), "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "streamlit" in out and "src/ui/app.py" in out and str(port) in out


def test_cli_print_config_is_json(capsys) -> None:
    port = _free_port()
    code = main(["--profile", "smart", "--port", str(port), "--print-config"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["profile"] == "smart"
    assert payload["remote_content_policy"] == "never"
    assert "ai_chat" in payload["capabilities"]


def test_cli_rejects_unknown_profile(capsys) -> None:
    code = main(["--profile", "nope", "--dry-run"])
    assert code == 2
    assert "unknown launch profile" in capsys.readouterr().err


def test_cli_forwards_passthrough_after_separator(capsys) -> None:
    port = _free_port()
    code = main(["--profile", "full", "--port", str(port), "--dry-run", "--", "--server.runOnSave=true"])
    out = capsys.readouterr().out
    assert code == 0
    assert "--server.runOnSave=true" in out


@pytest.mark.parametrize(
    ("shim", "profile"),
    [
        ("launchers/lite_mode.py", "lite"),
        ("launchers/smart_launcher.py", "smart"),
        ("launchers/launcher.py", "full"),
    ],
)
def test_historical_launchers_are_thin_wrappers(shim: str, profile: str) -> None:
    text = (REPO_ROOT / shim).read_text(encoding="utf-8")
    assert f'PROFILE = "{profile}"' in text
    assert "src.launcher" in text
    # No stale standalone Streamlit UI remains in the shims.
    assert "st.set_page_config" not in text
    assert "os.startfile" not in text


@pytest.mark.parametrize("script", ["run_lite.sh", "run_smart.sh", "run_full.sh"])
def test_shell_wrappers_target_the_launcher(script: str) -> None:
    text = (REPO_ROOT / "scripts" / script).read_text(encoding="utf-8")
    assert "-m src.launcher --profile" in text
    assert ".venv/bin/python" in text
