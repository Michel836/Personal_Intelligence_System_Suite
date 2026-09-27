"""Unified launcher for the canonical 36TB Intelligence app (M012-B2).

A single implementation serves every launch profile::

    python -m src.launcher --profile lite
    python -m src.launcher --profile smart
    python -m src.launcher --profile full

All profiles run ``src/ui/app.py`` (the canonical Streamlit app); they only
differ through profile defaults and capability exposure.  The historical
``launchers/*.py`` scripts are thin compatibility wrappers around this module.

Usage notes
-----------
* Explicit environment variables always win over profile defaults.
* An explicit ``--port`` / ``PIS_PORT`` is honoured as-is and fails loudly if it
  is occupied; a profile's preferred port is only a convenience and the launcher
  transparently selects a free port otherwise.
* Linux / macOS use ``.venv/bin/python``; Windows uses
  ``.venv\\Scripts\\python.exe``.  The launcher itself uses ``sys.executable`` so
  it works with either layout and in activated environments.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# Make ``import src...`` work whether this module is executed as
# ``python -m src.launcher`` or ``python src/launcher.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.core.launch_profile import (  # noqa: E402
    PREFERRED_PORTS,
    LaunchProfile,
    apply_profile_defaults,
    parse_profile,
    resolve_profile,
)

CANONICAL_APP = Path("src") / "ui" / "app.py"
_PORT_SCAN_LIMIT = 100


@dataclass
class LaunchPlan:
    """Fully resolved, side-effect-free description of a launch."""

    profile: LaunchProfile
    port: int
    host: str
    app_path: Path
    headless: bool
    open_browser: bool
    env: dict[str, str] = field(default_factory=dict)
    extra_streamlit_args: list[str] = field(default_factory=list)
    explicit_port: bool = False

    @property
    def command(self) -> list[str]:
        headless = "true" if self.headless else "false"
        return [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(self.app_path),
            "--server.port",
            str(self.port),
            "--server.address",
            self.host,
            "--server.headless",
            headless,
            "--browser.gatherUsageStats",
            "false",
            *self.extra_streamlit_args,
        ]

    def as_dict(self) -> dict[str, object]:
        contract = resolve_profile(self.profile, self.env)
        return {
            "profile": self.profile.value,
            "port": self.port,
            "host": self.host,
            "app": str(self.app_path),
            "headless": self.headless,
            "explicit_port": self.explicit_port,
            "url": f"http://{self.host}:{self.port}",
            "command": self.command,
            "capabilities": sorted(c.value for c in contract.capabilities),
            "env_defaults": contract.env_defaults,
            "ai_mode": self.env.get("PIS_AI_MODE", "auto"),
            "remote_content_policy": self.env.get("PIS_REMOTE_CONTENT_POLICY", "never"),
        }


# ---------------------------------------------------------------------------
# Port handling
# ---------------------------------------------------------------------------

def port_available(host: str, port: int) -> bool:
    """Whether *port* can be bound on *host* right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(host: str, preferred: int, *, limit: int = _PORT_SCAN_LIMIT) -> int:
    """Return the first free port at/after *preferred*.

    Raises :class:`RuntimeError` if no port is free within ``limit`` attempts.
    """
    for candidate in range(preferred, preferred + max(1, limit)):
        if port_available(host, candidate):
            return candidate
    raise RuntimeError(
        f"no free port found in range {preferred}-{preferred + limit - 1} on {host}"
    )


# ---------------------------------------------------------------------------
# Plan construction
# ---------------------------------------------------------------------------

def build_child_env(
    profile: LaunchProfile,
    *,
    port: int,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the app environment: profile defaults + explicit overrides.

    Profile defaults are applied with ``setdefault`` semantics, so any value the
    operator already set (API keys, AI mode, embedding backend, OCR, ...) is
    preserved verbatim.
    """
    env: dict[str, str] = dict(os.environ if base_env is None else base_env)
    apply_profile_defaults(profile, env)
    env["PIS_LAUNCH_PROFILE"] = profile.value
    env["PIS_PORT"] = str(port)
    return env


def build_plan(
    profile: LaunchProfile | str | None = None,
    *,
    port: int | None = None,
    host: str = "127.0.0.1",
    headless: bool = True,
    open_browser: bool = False,
    app_path: Path | None = None,
    extra_streamlit_args: Sequence[str] | None = None,
    base_env: Mapping[str, str] | None = None,
) -> LaunchPlan:
    """Resolve a :class:`LaunchPlan` without launching anything.

    An explicit ``port`` (argument or ``PIS_PORT``) is validated but never
    silently relocated; otherwise the profile's preferred port is used if free
    and the next free port is chosen on conflict.
    """
    env = dict(os.environ if base_env is None else base_env)
    resolved = parse_profile(profile, strict=True) if profile is not None else parse_profile(
        env.get("PIS_LAUNCH_PROFILE"), strict=False
    )

    env_port = env.get("PIS_PORT", "").strip()
    explicit_port = port is not None or bool(env_port)
    requested = port if port is not None else (int(env_port) if env_port.isdigit() else None)

    if requested is None:
        selected = find_free_port(host, PREFERRED_PORTS[resolved])
    else:
        if not port_available(host, requested):
            raise RuntimeError(f"port {requested} is already in use on {host}")
        selected = requested

    root = _REPO_ROOT
    target = (root / (app_path or CANONICAL_APP)).resolve()
    child_env = build_child_env(resolved, port=selected, base_env=env)

    return LaunchPlan(
        profile=resolved,
        port=selected,
        host=host,
        app_path=target,
        headless=headless,
        open_browser=open_browser,
        env=child_env,
        extra_streamlit_args=list(extra_streamlit_args or []),
        explicit_port=explicit_port,
    )


def launch(plan: LaunchPlan) -> int:
    """Run the canonical app for *plan* (blocking)."""
    if not plan.app_path.exists():
        sys.stderr.write(f"canonical app not found: {plan.app_path}\n")
        return 2
    sys.stdout.write(
        f"[PIS] profile={plan.profile.value} url=http://{plan.host}:{plan.port} "
        f"ai_mode={plan.env.get('PIS_AI_MODE')} "
        f"remote_policy={plan.env.get('PIS_REMOTE_CONTENT_POLICY')}\n"
    )
    sys.stdout.flush()
    try:
        return subprocess.call(plan.command, cwd=str(_REPO_ROOT), env=plan.env)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.launcher",
        description="Launch the canonical 36TB Intelligence app with a profile.",
    )
    parser.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="launch profile: lite | smart | full (default: PIS_LAUNCH_PROFILE or full)",
    )
    parser.add_argument("--profile", dest="profile_opt", default=None, help="launch profile")
    parser.add_argument("--port", type=int, default=None, help="explicit port (fails if occupied)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        default=True,
        help="run Streamlit headless (default)",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="run Streamlit with the browser UI enabled",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="hint Streamlit to open a browser (not used for headless servers)",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="print the resolved launch plan as JSON and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the command that would run and exit",
    )
    parser.add_argument(
        "--app",
        default=None,
        help="override the app path (advanced; defaults to the canonical app)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    # Unknown options are forwarded verbatim to `streamlit run`.  Everything
    # after an explicit ``--`` is passed through unchanged; otherwise
    # parse_known_args collects stray options while still allowing `--flag`
    # after an optional positional profile (argparse.REMAINDER would swallow it).
    raw = list(argv) if argv is not None else sys.argv[1:]
    after_separator: list[str] = []
    if "--" in raw:
        split = raw.index("--")
        raw, after_separator = raw[:split], raw[split + 1 :]
    args, unknown = parser.parse_known_args(raw)
    passthrough = list(unknown) + after_separator

    chosen = args.profile_opt or args.profile
    if chosen is None:
        chosen = os.environ.get("PIS_LAUNCH_PROFILE") or LaunchProfile.FULL.value
    try:
        profile = parse_profile(chosen, strict=True)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    app_path = Path(args.app) if args.app else None
    try:
        plan = build_plan(
            profile,
            port=args.port,
            host=args.host,
            headless=args.headless,
            open_browser=args.open_browser,
            app_path=app_path,
            extra_streamlit_args=passthrough,
        )
    except (RuntimeError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    if args.print_config:
        sys.stdout.write(json.dumps(plan.as_dict(), indent=2) + "\n")
        return 0
    if args.dry_run:
        sys.stdout.write(" ".join(plan.command) + "\n")
        return 0
    return launch(plan)


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
