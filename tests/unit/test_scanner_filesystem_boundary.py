from pathlib import Path
from types import SimpleNamespace

from src.scanner.fast_engine import FastScannerEngine


def test_fast_scan_does_not_cross_filesystem_boundary(monkeypatch):
    scanner = FastScannerEngine()
    root = Path("/scan")

    def fake_walk(_root):
        yield "/scan", ["local", "foreign"], ["root.txt"]
        yield "/scan/local", [], ["local.txt"]
        yield "/scan/foreign", ["nested"], ["foreign.txt"]
        yield "/scan/foreign/nested", [], ["hidden.txt"]

    def fake_device(path):
        path = Path(path)
        if str(path).startswith("/scan/foreign"):
            return 2
        return 1

    def fake_extract(path):
        return SimpleNamespace(path=Path(path), size_bytes=1)

    monkeypatch.setattr("src.scanner.fast_engine.os.walk", fake_walk)
    monkeypatch.setattr(scanner, "_filesystem_device", fake_device)
    monkeypatch.setattr(scanner, "_extract_file_info_fast", fake_extract)

    files = list(scanner.fast_scan(root))

    assert [str(item.path) for item in files] == [
        "/scan/root.txt",
        "/scan/local/local.txt",
    ]


def test_fast_scan_refuses_root_when_filesystem_identity_is_unavailable(monkeypatch):
    scanner = FastScannerEngine()
    monkeypatch.setattr(scanner, "_filesystem_device", lambda _path: None)

    assert list(scanner.fast_scan(Path("/missing"))) == []
    assert scanner.is_running is False
