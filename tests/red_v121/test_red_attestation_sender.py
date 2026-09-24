"""RED: PR-012 half 2 remainder -- the Rust attestation sender (R16).

Half 2 landed the Core-side receiver and gate.  What is still missing is the
**sender**: nothing in Rust ever reports a verdict to Core, so at runtime no
attestation arrives, the gate stays closed and Hub control is permanently denied.
That state is safe (fail-closed) but not functional.

Approved design (docs/PR-012-ATTESTATION-CHANNEL-DESIGN.md): Rust sends the
attestation to Core over the **existing authenticated WS** -- Rust is the WS
client, Core the server, and the Tauri event channel is not involved.  The
contract already carries the inbound ``hub.attest_bind`` command.

These are structural assertions on the Rust source.  The behavioural proof (a
real WS frame carrying a real verdict) needs a live Core and belongs to the
interop probe, which is not run here.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

SRC = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src"
LIB_RS = SRC / "lib.rs"


def _sender_body(src: str) -> str:
    r"""Return the body of the function that emits the attestation command.

    Located by the command literal rather than by a name pattern: a name pattern
    like ``\w*attest\w*`` also matches ``observe_hub_bind_attestation``, which is
    the *observer*, so a name-based lookup would silently assert against the wrong
    function (this helper replaced exactly that mistake).
    """
    for match in re.finditer(r"fn\s+(\w+)\s*\([^)]*\)[^{]*\{(.*?)\n\}", src, re.S):
        if '"hub.attest_bind"' in match.group(2):
            return match.group(2)
    raise AssertionError(
        "no function emits the `hub.attest_bind` command; Rust never reports an "
        "attestation, so the Core gate can never open"
    )


# --------------------------------------------------------- the command is sent
def test_rust_sends_the_attestation_command():
    src = read_text(LIB_RS)
    assert '"hub.attest_bind"' in src, (
        "nothing in Rust emits the `hub.attest_bind` command, so no attestation "
        "ever reaches Core and the control gate can never open"
    )


def test_the_command_carries_the_attestation_payload():
    """The envelope must be shaped as Core's contract expects."""
    src = read_text(LIB_RS)
    body = _sender_body(src)
    assert '"attestation"' in body, (
        "the payload must nest the verdict under `attestation` (Core's "
        "HubAttestBindPayload shape)"
    )


def test_sender_reuses_the_observation_it_already_produces():
    """The verdict must come from the PR-008 observer, not a second probe."""
    src = read_text(LIB_RS)
    assert "observe_hub_bind_attestation" in src, (
        "the sender must reuse `observe_hub_bind_attestation`; a second, "
        "independently written probe would let the two disagree"
    )
    # The observer is called from more than its own definition site.
    assert src.count("observe_hub_bind_attestation") >= 2, (
        "`observe_hub_bind_attestation` is currently only defined and called by "
        "the WebView reader; the sender must call it too"
    )


# ------------------------------------------------------------- revalidation
def test_attestation_is_refreshed_not_sent_once():
    """Plan L665 is a continuing condition: a one-shot send is not enough.

    The Core gate expires a verdict via ``revalidate_after``, so Rust must
    re-attest on a cadence or the gate would close on its own and stay closed.
    """
    src = read_text(LIB_RS)
    assert re.search(r"attest.*interval|REATTEST|revalidate", src, re.I), (
        "Rust must re-attest periodically; otherwise the Core-side "
        "`revalidate_after` deadline expires and control is permanently denied"
    )


def test_sender_does_not_block_the_ui_thread():
    """`send_command` blocks until correlated; the caller must not be the UI.

    The property is about the *call site*, not the sender's own body: the sender
    may legitimately be a plain function as long as something spawns a thread that
    drives it.  (An earlier version of this test asserted `spawn` inside the
    sender body, which would have forced a pointless nested spawn.)
    """
    src = read_text(LIB_RS)
    _sender_body(src)  # fails loudly if no sender exists
    assert re.search(r"spawn\w*\s*\([^)]*\)[\s\S]{0,400}?send_bind_attestation", src), (
        "nothing spawns a thread that calls the attestation sender, so it would "
        "run on the UI/IPC thread and block it for up to the command timeout"
    )


def test_sender_is_not_called_from_a_tauri_command_handler():
    """A `#[tauri::command]` handler runs on the IPC thread and must not block."""
    src = read_text(LIB_RS)
    for match in re.finditer(
        r"#\[tauri::command\][\s\S]{0,80}?fn\s+(\w+)\s*\([^)]*\)[^{]*\{(.*?)\n\}",
        src,
        re.S,
    ):
        assert "send_bind_attestation" not in match.group(2), (
            f"the Tauri command `{match.group(1)}` must not call the blocking "
            "attestation sender directly"
        )


def test_sender_failure_is_reported_not_silent():
    """A failed attestation send must be visible; silence would look like a bind."""
    src = read_text(LIB_RS)
    body = _sender_body(src)
    assert "log::" in body or "eprintln!" in body, (
        "the sender must log its outcome; a silently dropped attestation is "
        "indistinguishable from a closed gate and would be very hard to diagnose"
    )
