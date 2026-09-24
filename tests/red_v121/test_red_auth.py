"""RED: v1.2.1 fail-closed authentication (feeds R05).

Frozen rules (v1.2.1 §Phase 1 + PR-006 acceptance):
* Private HTTP/WS entry points must reject unauthenticated clients.
* The bearer token may only arrive via the bootstrap pipe - never argv, never a
  URL/query string, never a log, never the WebView.
* Origin is an additional check: only the native bridge's fixed values are
  allowed; a generic ``http://localhost`` origin is NOT sufficient.

Current state: the server builds ``TokenValidator(require_auth=False)``, accepts
``--token`` on the CLI and reads the WS token from query params.
"""
from __future__ import annotations

import pytest

from harness import REPO_ROOT, read_text
from lva.transport.auth import TokenValidator

pytestmark = pytest.mark.red_v121

SERVER = REPO_ROOT / "src" / "lva" / "server.py"
MAIN = REPO_ROOT / "src" / "lva" / "__main__.py"


# ------------------------------------------------------------ runtime default
def test_token_validator_defaults_to_requiring_auth():
    v = TokenValidator()
    assert v.require_auth is True, "TokenValidator must default to fail-closed"
    assert v.verify_token(None) is False, "no token must never be accepted"


def test_server_does_not_disable_auth():
    src = read_text(SERVER)
    assert "require_auth=False" not in src, (
        "server.py constructs the auth middleware with require_auth=False, which "
        "leaves every private route unauthenticated (v1.2.1 PR-006)"
    )


def test_server_requires_a_token_to_be_configured():
    """Fail closed: a private server without a configured token must not serve."""
    v = TokenValidator(require_auth=True)
    assert v.expected_token is None
    assert v.verify_token("anything") is False, (
        "when no expected token is configured, no client token may be accepted"
    )


# ------------------------------------------------------------------- CLI/argv
def test_cli_has_no_token_flag():
    src = read_text(MAIN)
    assert '"--token"' not in src, (
        "the CLI exposes --token, putting the runtime token into argv; "
        "v1.2.1 hard constraint #5 forbids this"
    )


# ---------------------------------------------------------------- WS / Origin
def test_websocket_does_not_accept_token_from_query():
    src = read_text(SERVER)
    assert 'query_params.get("token")' not in src, (
        "the WebSocket reads the bearer token from the query string; tokens must "
        "not travel in URLs (v1.2.1 PR-006)"
    )


def test_origin_policy_rejects_generic_localhost():
    v = TokenValidator(require_auth=True)
    assert v.verify_origin("http://localhost:1234") is False, (
        "a generic http://localhost origin must be rejected; only the native "
        "bridge's fixed origins are allowed (v1.2.1 §Phase 1)"
    )
    assert v.verify_origin("http://127.0.0.1:5173") is False, (
        "an arbitrary loopback dev-server origin must be rejected"
    )


def test_origin_policy_accepts_native_bridge_origin():
    v = TokenValidator(require_auth=True)
    assert v.verify_origin("tauri://localhost") is True, (
        "the native Tauri origin must remain allowed"
    )


def test_origin_policy_rejects_remote_origin():
    v = TokenValidator(require_auth=True)
    assert v.verify_origin("https://evil.example.com") is False