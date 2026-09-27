"""Release acceptance for profiles, launcher and instance safety (M021)."""
from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.core.launch_profile import (
    ADVANCED_CAPABILITIES,
    CORE_CAPABILITIES,
    PREFERRED_PORTS,
    Capability,
    LaunchProfile,
    apply_profile_defaults,
    capabilities_for,
    resolve_profile,
)
from src.launcher import build_plan, find_free_port, port_available
from src.ops.instance import InstanceError, InstanceLock


@pytest.mark.parametrize("profile", [LaunchProfile.LITE, LaunchProfile.SMART,
                                     LaunchProfile.FULL])
def test_profile_contracts_and_privacy_default(profile: LaunchProfile) -> None:
    contract = resolve_profile(profile, {})
    assert Capability.SEARCH in contract.capabilities
    assert Capability.SCAN in contract.capabilities
    assert contract.env_defaults["PIS_REMOTE_CONTENT_POLICY"] == "never"
    assert contract.env_defaults["PIS_HEAVY_PRELOAD"] == "0"
    assert contract.preferred_port == PREFERRED_PORTS[profile]


def test_lite_hides_advanced_profiles_expose_them() -> None:
    lite = capabilities_for(LaunchProfile.LITE, {})
    assert not (ADVANCED_CAPABILITIES & lite)
    for profile in (LaunchProfile.SMART, LaunchProfile.FULL):
        assert capabilities_for(profile, {}) >= ADVANCED_CAPABILITIES
    assert capabilities_for(LaunchProfile.FULL, {}) >= CORE_CAPABILITIES


def test_explicit_env_always_wins_over_profile_defaults() -> None:
    env = {"PIS_AI_MODE": "local", "PIS_REMOTE_CONTENT_POLICY": "never"}
    apply_profile_defaults(LaunchProfile.FULL, env)
    assert env["PIS_AI_MODE"] == "local"  # not overwritten by profile default "auto"


def test_launch_plan_uses_canonical_app_and_honours_explicit_port() -> None:
    free = find_free_port("127.0.0.1", 8791)
    plan = build_plan(LaunchProfile.SMART, port=free)
    assert plan.app_path.name == "app.py"
    assert plan.port == free and plan.explicit_port is True
    command = plan.command
    assert "streamlit" in command and "--server.headless" in command
    assert plan.as_dict()["remote_content_policy"] == "never"


def test_port_collision_is_detected() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert port_available("127.0.0.1", port) is False
        with pytest.raises(RuntimeError):
            build_plan(LaunchProfile.FULL, port=port)


def test_instance_lock_and_stale_recovery(tmp_path: Path) -> None:
    lock = InstanceLock("release", directory=tmp_path)
    lock.acquire()
    assert lock.read() is not None
    lock.release()
    assert lock.read() is None
    # Stale (dead-pid) lock is reclaimed automatically.
    (tmp_path / "release.lock").write_text(
        '{"pid": 999999, "name": "release", "started_at": 0}', encoding="utf-8")
    reclaimed = InstanceLock("release", directory=tmp_path)
    reclaimed.acquire()
    assert reclaimed.read() is not None
    reclaimed.release()


def test_instance_lock_refuses_a_live_owner(tmp_path: Path) -> None:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (tmp_path / "release.lock").write_text(
            f'{{"pid": {proc.pid}, "name": "release", "started_at": 0}}', encoding="utf-8")
        with pytest.raises(InstanceError):
            InstanceLock("release", directory=tmp_path).acquire()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_profile_module_does_not_import_heavy_runtime() -> None:
    code = ("import src.core.launch_profile as p, sys; "
            "print('streamlit' in sys.modules, 'torch' in sys.modules, "
            "'sentence_transformers' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path(__file__).resolve().parents[2]), check=True).stdout
    assert out.strip() == "False False False"
