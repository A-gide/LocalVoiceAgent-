"""Shared test isolation for server paths that would otherwise touch repo data."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def isolated_server_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    from lva import config as C
    import lva.server as server

    monkeypatch.setattr(C, "DATA", tmp_path)
    monkeypatch.setattr(server, "_journal", None)
    monkeypatch.setattr(server, "_runtime", None)
    monkeypatch.setattr(server, "_core", None)
    yield tmp_path
    if server._journal is not None:
        server._journal.conn.close()
