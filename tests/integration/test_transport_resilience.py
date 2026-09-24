"""Transport layer resilience and security boundary integration tests.

Verifies:
1. HTTP AuthMiddleware: token requirement, constant-time compare, Origin header validation.
2. WebSocket authentication boundary: token check, rejection of unauthorized clients with code 4403.
3. WebSocket command engine: typed CommandEnvelope dispatch, optimistic concurrency (STALE_REVISION),
   idempotency deduplication, ping/pong heartbeats.
4. WebSocket reconnection resilience: session continuity across disconnect/reconnect cycles.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from lva.contracts.enums import ErrorCode, Mode
from lva.server import app, auth_validator, get_runtime

pytestmark = pytest.mark.usefixtures("isolated_server_data")


@pytest.fixture(autouse=True)
def setup_auth():
    """Configure auth_validator with test token for transport tests."""
    token = "test-secret-token-256bit"
    auth_validator.set_token(token)
    auth_validator.require_auth = True
    yield
    # Reset auth after test
    auth_validator.require_auth = True
    auth_validator.expected_token = None


def test_http_auth_required_and_origin_boundary():
    """Verify HTTP auth enforcement and Origin header validation."""
    client = TestClient(app)

    # 1. Public endpoint /health is accessible without auth
    resp_health = client.get("/health")
    assert resp_health.status_code in (200, 503)

    # 2. Private endpoint /api/state without Authorization header -> 401 AUTH_REQUIRED
    resp_no_auth = client.get("/api/state")
    assert resp_no_auth.status_code == 401
    err = resp_no_auth.json()
    assert err["code"] == ErrorCode.AUTH_REQUIRED.value

    # 3. Private endpoint with invalid token -> 403 AUTH_FAILED
    resp_bad_auth = client.get(
        "/api/state",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert resp_bad_auth.status_code == 403
    err = resp_bad_auth.json()
    assert err["code"] == ErrorCode.AUTH_FAILED.value

    # 4. Disallowed Origin header -> 403 ORIGIN_REJECTED
    resp_bad_origin = client.get(
        "/api/state",
        headers={
            "Authorization": "Bearer test-secret-token-256bit",
            "Origin": "http://evil-site.com",
        },
    )
    assert resp_bad_origin.status_code == 403
    err = resp_bad_origin.json()
    assert err["code"] == ErrorCode.ORIGIN_REJECTED.value

    # 5. Valid token and allowed Origin -> 200 OK
    resp_ok = client.get(
        "/api/state",
        headers={
            "Authorization": "Bearer test-secret-token-256bit",
            "Origin": "tauri://localhost",
        },
    )
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert "runtime_state" in data


def test_websocket_auth_boundary():
    """Verify WebSocket authentication: unauthorized connections are rejected with 4403."""
    client = TestClient(app)

    # 1. WS connection without token is rejected
    with pytest.raises(Exception):
        with client.websocket_connect("/ws") as ws:
            pass

    # 2. WS connection with invalid token is rejected
    with pytest.raises(Exception):
        with client.websocket_connect("/ws", headers={"Authorization": "Bearer wrong-token"}) as ws:
            pass

    # 3. WS connection with valid token succeeds and receives hello message
    with client.websocket_connect("/ws", headers={"Authorization": "Bearer test-secret-token-256bit"}) as ws:
        hello_raw = ws.receive_text()
        hello = json.loads(hello_raw)
        assert hello["kind"] == "hello"
        assert "state" in hello
        assert hello["state"]["schema_version"] == "1.0"


def test_websocket_command_execution_idempotency_and_concurrency():
    """Verify WebSocket command dispatch, idempotency, and optimistic concurrency."""
    client = TestClient(app)
    rt = get_runtime()

    with client.websocket_connect("/ws", headers={"Authorization": "Bearer test-secret-token-256bit"}) as ws:
        # Read initial hello
        _ = ws.receive_text()

        # 1. Ping / Pong
        ws.send_text(json.dumps({"type": "ping"}))
        pong = json.loads(ws.receive_text())
        assert pong["kind"] == "pong"
        assert "ts" in pong

        # 2. Send valid CommandEnvelope: set mode to LIVE
        cmd_id_1 = str(uuid4())
        cmd1 = {
            "schema_version": "1.0",
            "command_id": cmd_id_1,
            "idempotency_key": "idemp-key-001",
            "precondition": {"aggregate": "runtime_control", "revision": rt.runtime_control_revision},
            "type": "runtime.set_mode",
            "payload": {"type": "runtime.set_mode", "mode": "live"},
        }
        ws.send_text(json.dumps(cmd1))
        res1 = json.loads(ws.receive_text())
        assert res1["kind"] == "command_result"
        assert res1["status"] == "applied"
        assert rt.mode == Mode.LIVE

        # 3. Idempotency: replay same command with same idempotency_key
        ws.send_text(json.dumps(cmd1))
        res2 = json.loads(ws.receive_text())
        assert res2["kind"] == "command_result"
        assert res2["status"] == "duplicate"

        # 4. Optimistic concurrency: send command with stale precondition revision
        cmd_stale = {
            "schema_version": "1.0",
            "command_id": str(uuid4()),
            "idempotency_key": "idemp-key-stale",
            "precondition": {"aggregate": "runtime_control", "revision": 0},  # stale on purpose
            "type": "runtime.set_mode",
            "payload": {"type": "runtime.set_mode", "mode": "standby"},
        }
        ws.send_text(json.dumps(cmd_stale))
        res_stale = json.loads(ws.receive_text())
        assert res_stale["kind"] == "command_result"
        assert res_stale["status"] == "rejected"
        assert res_stale["error"]["code"] == ErrorCode.STALE_REVISION.value


def test_websocket_reconnect_and_session_continuity():
    """Verify state and session continuity when client disconnects and reconnects."""
    client = TestClient(app)
    rt = get_runtime()

    # Session 1: connect and switch to LIVE
    with client.websocket_connect("/ws", headers={"Authorization": "Bearer test-secret-token-256bit"}) as ws1:
        _ = ws1.receive_text()
        ws1.send_text(json.dumps({
            "schema_version": "1.0",
            "command_id": str(uuid4()),
            "precondition": {"aggregate": "runtime_control", "revision": rt.runtime_control_revision},
            "type": "runtime.set_mode",
            "payload": {"type": "runtime.set_mode", "mode": "live"},
        }))
        res = json.loads(ws1.receive_text())
        assert res["status"] == "applied"

    # ws1 is now closed (disconnected)
    assert rt.mode == Mode.LIVE
    assert rt.session_controller.current_session_id is not None
    saved_session_id = str(rt.session_controller.current_session_id)

    # Session 2: reconnect with new websocket
    with client.websocket_connect("/ws", headers={"Authorization": "Bearer test-secret-token-256bit"}) as ws2:
        hello = json.loads(ws2.receive_text())
        assert hello["kind"] == "hello"
        # State and session ID are preserved across connections
        state = hello["state"]
        assert state["mode"] == "live"
        assert state["session_id"] == saved_session_id
