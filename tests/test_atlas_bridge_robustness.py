#!/usr/bin/env python3
"""Hermetic tests for the Atlas bridge robustness fixes (2026-06-27 audit).

No real Atlas worker is spawned — we drive AtlasTools with fake stdin/stdout
streams to exercise the failure paths:

- a failed ping handshake leaves the worker None and _send_request returns a
  clean error instead of dereferencing None (was AttributeError);
- request ids are monotonic (no id=0 / hash collisions);
- a stale valid-JSON response with the wrong id is skipped, not returned;
- _reset_worker terminates and clears the worker.
"""
import asyncio
import json

import pytest

from core import atlas_tools
from core.atlas_tools import AtlasTools


class _FakeStdin:
    def __init__(self):
        self.buf = b""

    def write(self, data):
        self.buf += data

    async def drain(self):
        pass

    def is_closing(self):
        return False


class _FakeStdout:
    """Yields pre-seeded lines, then blocks (simulates no more output)."""
    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        await asyncio.sleep(3600)  # never returns within test timeout


class _FakeProc:
    def __init__(self, lines):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(lines)
        self.stderr = None
        self.returncode = None
        self.killed = False

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


def _tools_with_worker(lines):
    t = AtlasTools.__new__(AtlasTools)
    t.available = True
    t._worker = _FakeProc(lines)
    t._lock = asyncio.Lock()
    t._req_id = 0
    return t


def test_next_id_is_monotonic():
    t = AtlasTools.__new__(AtlasTools)
    t._req_id = 0
    ids = [t._next_id() for _ in range(5)]
    assert ids == [1, 2, 3, 4, 5]
    assert len(set(ids)) == 5


def test_atlas_path_helpers_honor_env_overrides(monkeypatch):
    monkeypatch.setenv("AMY_ATLAS_ROOT", "/tmp/custom-atlas")
    monkeypatch.setenv("AMY_ATLAS_PYTHON", "/tmp/custom-atlas-python")

    root = atlas_tools._resolve_atlas_root()
    python = atlas_tools._resolve_atlas_python(root)

    assert str(root) == "/tmp/custom-atlas"
    assert str(python) == "/tmp/custom-atlas-python"


async def test_send_request_matches_by_id():
    # Worker replies to request id=1 with a correctly-id'd line.
    t = _tools_with_worker([json.dumps({"id": 1, "result": "pong"}).encode() + b"\n"])
    resp = await t._send_request({"id": 1, "action": "ping"})
    assert resp["result"] == "pong"


async def test_stale_wrong_id_response_is_skipped_then_matched():
    # A leftover response for a previous request (id=0) precedes the real one.
    lines = [
        json.dumps({"id": 0, "result": "STALE"}).encode() + b"\n",
        json.dumps({"id": 7, "result": "fresh"}).encode() + b"\n",
    ]
    t = _tools_with_worker(lines)
    resp = await t._send_request({"id": 7, "action": "run_tool"})
    assert resp["result"] == "fresh", "stale wrong-id response must not be returned"


async def test_send_request_returns_error_when_worker_unavailable(monkeypatch):
    # _ensure_worker leaves the worker None (handshake failure simulation).
    t = AtlasTools.__new__(AtlasTools)
    t.available = True
    t._worker = None
    t._lock = asyncio.Lock()
    t._req_id = 0

    async def _fake_ensure():
        t._worker = None  # stays down

    monkeypatch.setattr(t, "_ensure_worker", _fake_ensure)
    resp = await t._send_request({"id": 1, "action": "ping"})
    assert "error" in resp
    assert resp["error"] == "Atlas worker unavailable"


async def test_reset_worker_kills_and_clears():
    t = _tools_with_worker([])
    proc = t._worker
    await t._reset_worker()
    assert proc.killed is True
    assert t._worker is None


async def test_worker_closed_stream_resets_and_errors():
    # An empty bytes readline means stdout EOF — worker dead.
    t = _tools_with_worker([b""])
    resp = await t._send_request({"id": 1, "action": "ping"})
    assert resp["error"] == "Worker closed output stream"
    assert t._worker is None  # reset so next call respawns
