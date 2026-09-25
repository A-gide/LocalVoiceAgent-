"""RED: the window remembers where it was dragged, and events reconnect.

Two remaining S-UI-01 gaps (§1.5 and §1.7):

* "crash/restart geometry restore -- failed (not implemented)": the position was
  never written back, so even after R30 taught the shell to *restore* a position
  there was nothing new to restore.  A window the user carefully placed came back
  at the default spot on every restart.
* "WebView2 reload and event reconnection -- failed": `listen("lva://event")` was
  subscribed once on mount.  A Tauri window that reloads its WebView (dev-server
  refresh, a renderer crash) loses the subscription silently and the UI keeps
  rendering stale state with no error.

Both are about the same thing: state that must survive something going away.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

UI = REPO_ROOT / "apps" / "desktop-ui" / "src"
GEOMETRY = UI / "composables" / "window" / "useWindowGeometry.ts"
BRIDGE = UI / "bridge" / "tauri-bridge.ts"
APP = UI / "app" / "App.vue"


# ------------------------------------------------------- geometry write-back
def test_the_composable_can_persist_the_current_position() -> None:
    """Without a write-back, restore has nothing to restore."""
    src = read_text(GEOMETRY)
    assert "persistCurrent" in src, (
        "the composable must expose a way to save where the window is now"
    )
    assert "setWindowGeometry" in src, (
        "persisting must go through the Rust command, not a local variable"
    )


def test_the_character_view_persists_after_a_move() -> None:
    """A drag must be recorded, or the placement is lost on restart."""
    src = read_text(UI / "features" / "character" / "CharacterView.vue")
    # The move subscription itself belongs in the composable (that is where the
    # Tauri API calls live); the view owns starting and stopping it.
    assert "watchPosition" in src, (
        "CharacterView must observe window moves and persist them; otherwise a "
        "position the user chose is forgotten on every restart"
    )
    assert "persistCurrent" in src, (
        "the view must own the persist lifecycle it started"
    )


def test_persistence_is_debounced_rather_than_per_pixel() -> None:
    """A drag emits a move event per frame; writing each one is wasteful."""
    src = read_text(GEOMETRY)
    m = re.search(r"(?:debounce|setTimeout|clearTimeout|throttle)", src)
    assert m, (
        "persisting on every move event would write the settings file hundreds of "
        "times per drag; the write must be debounced"
    )


# ------------------------------------------------------------ event reconnect
def test_the_bridge_can_resubscribe_after_a_dropped_listener() -> None:
    """A reloaded WebView must be able to restore its subscription."""
    src = read_text(BRIDGE)
    assert "resubscribe" in src or "subscribeWithRetry" in src or "ensureEventSubscription" in src, (
        "the bridge needs an idempotent subscribe that can be called again after a "
        "reload; a one-shot listen leaves the UI silently stale"
    )


def test_the_app_uses_the_resubscribing_path() -> None:
    src = read_text(APP)
    assert "ensureEventSubscription" in src or "resubscribe" in src, (
        "App.vue must subscribe through the path that can be re-established"
    )


def test_a_stale_subscription_is_replaced_rather_than_duplicated() -> None:
    """Two live listeners would double-apply every event."""
    src = read_text(BRIDGE)
    assert re.search(r"unlisten|UnlistenFn|_unlisten", src), (
        "the previous listener must be released when re-subscribing, or each reload "
        "adds another listener and every event is handled twice"
    )
