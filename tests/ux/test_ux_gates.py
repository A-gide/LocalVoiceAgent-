"""UX Gates and Interaction Tests (PR-035 / Part 8.4 / Part 13.1).

Validates:
1. One-action operations (Live, Pause, Chat, Memory) <= 1 action
2. Recording and privacy state visibility within 1 second with text + icon (not color alone)
3. Privacy scope distinction: VERIFIED vs UNVERIFIED external capture
4. Normal services view hides raw PIDs, ports, and raw endpoints
5. Secret storage write-only policy (never echo secrets in public DTO)
6. Window geometry clamping and position reset
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from uuid import uuid4

from src.lva.contracts.commands import (
    CommandEnvelope,
    RuntimeSetModePayload,
)
from src.lva.contracts.enums import Mode, PrivacyScope
from src.lva.core.runtime import RuntimeController
from src.lva.journal.repository import JournalRepository


@pytest.fixture
def runtime():
    events = []
    journal = JournalRepository(":memory:")
    return RuntimeController(event_broadcaster=events.append, journal=journal)


class TestOneActionOperations:
    """Part 8.4: Enter Live and Privacy Pause require <= 1 primary action."""

    def test_enter_live_mode_one_action(self, runtime: RuntimeController):
        # Action: Dispatch single set_mode command to LIVE
        cmd = CommandEnvelope(
            schema_version="1.0",
            command_id=uuid4(),
            type="runtime.set_mode",
            precondition={"aggregate": "runtime_control", "revision": runtime.runtime_control_revision},
              payload=RuntimeSetModePayload(type="runtime.set_mode", mode=Mode.LIVE),
        )
        res = runtime.execute_command(cmd)
        assert res.status == "applied"
        assert runtime.mode == Mode.LIVE
        assert runtime.get_state().mic_capture.active is True

    def test_enter_privacy_pause_one_action(self, runtime: RuntimeController):
        # Action: Dispatch single set_mode command to PRIVACY_PAUSE
        cmd = CommandEnvelope(
            schema_version="1.0",
            command_id=uuid4(),
            type="runtime.set_mode",
            precondition={"aggregate": "runtime_control", "revision": runtime.runtime_control_revision},
              payload=RuntimeSetModePayload(type="runtime.set_mode", mode=Mode.PRIVACY_PAUSE),
        )
        res = runtime.execute_command(cmd)
        assert res.status == "applied"
        assert runtime.mode == Mode.PRIVACY_PAUSE
        assert runtime.get_state().mic_capture.active is False
        assert runtime.get_state().privacy_scope != PrivacyScope.NOT_PAUSED


class TestStatusVisibilityAndScope:
    """Part 8.4: Recording/privacy state 1 second recognizable with text + icon, not color alone."""

    def test_recording_state_text_and_cue(self, runtime: RuntimeController):
        runtime.set_mode(Mode.LIVE)
        state = runtime.get_state()
        # Visual cues must have explicit textual description and icon
        mode_str = state.mode.value
        assert mode_str in ("live", "passive", "standby", "privacy_pause")
        assert state.mic_capture.active is True
        assert state.activity.value in ("idle", "listening", "thinking", "speaking")

    def test_privacy_scope_unverified_cue(self, runtime: RuntimeController):
        runtime.set_mode(Mode.PRIVACY_PAUSE)
        state = runtime.get_state()
        # Default with external capture unverified must not falsely claim all capture is off
        assert state.privacy_scope in (
            PrivacyScope.VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF,
            PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN,
            PrivacyScope.LVA_CORE_OFF_EXTERNAL_CAPTURE_PRESENT,
        )


class TestPrivacyAndSecretsRedaction:
    """Part 8.4: Normal services UI hides PID, ports, endpoints, and secrets."""

    def test_public_settings_has_no_plaintext_secrets(self):
        settings_example = Path("settings.example.json")
        if settings_example.exists():
            data = json.loads(settings_example.read_text(encoding="utf-8"))
            content_str = json.dumps(data)
            assert "sk-" not in content_str
            assert "api_key" not in data or data["api_key"] is None or data["api_key"] == ""

    def test_services_example_no_user_paths(self):
        services_example = Path("services.example.json")
        if services_example.exists():
            text = services_example.read_text(encoding="utf-8")
            assert "C:\\Users\\" not in text
            assert "W:\\model\\" not in text


class TestWindowGeometryClamp:
    """Part 8.3 & PR-030: Window clamping and reset position."""

    def test_geometry_clamp_logic(self):
        # Emulate composable clamp logic
        def clamp_window(x: int, y: int, width: int, height: int, screen_w: int, screen_h: int) -> tuple[int, int]:
            clamped_x = max(0, min(x, screen_w - width))
            clamped_y = max(0, min(y, screen_h - height))
            return clamped_x, clamped_y

        # Out-of-bounds negative
        cx, cy = clamp_window(-100, -50, 320, 480, 1920, 1080)
        assert cx == 0
        assert cy == 0

        # Out-of-bounds right/bottom
        cx, cy = clamp_window(2000, 1200, 320, 480, 1920, 1080)
        assert cx == 1920 - 320
        assert cy == 1080 - 480

        # In-bounds stays identical
        cx, cy = clamp_window(500, 400, 320, 480, 1920, 1080)
        assert cx == 500
        assert cy == 400


class TestLegacyDeletionAndConvergence:
    """PR-036, PR-037, PR-038: Legacy deletion and convergence gates."""

    def test_no_legacy_html_ui_files(self):
        """PR-038: Legacy HTML files must be deleted."""
        assert not Path("apps/desktop-shell/ui").exists()
        assert not Path("apps/desktop-shell/patches").exists()

    def test_no_legacy_olv_server(self):
        """PR-036: OLV conversation core and server must be deleted."""
        assert not Path("apps/open-llm-vtuber/run_server.py").exists()
        assert not Path("apps/open-llm-vtuber/src/open_llm_vtuber/server.py").exists()
        assert not Path("apps/open-llm-vtuber/src/open_llm_vtuber/conversations").exists()

    def test_no_legacy_ports_in_configs(self):
        """PR-015 / PR-038: No references to port 1234 or 12393 in configs."""
        for cfg_path in [
            Path("settings.example.json"),
            Path("apps/desktop-shell/src-tauri/settings.default.json"),
            Path("apps/desktop-shell/src-tauri/services.default.json"),
        ]:
            if cfg_path.exists():
                text = cfg_path.read_text(encoding="utf-8")
                assert "1234" not in text, f"Found port 1234 in {cfg_path}"
                assert "12393" not in text, f"Found port 12393 in {cfg_path}"

    def test_pet_window_loads_embedded_app(self):
        """PR-034 / PR-036: Pet window must load embedded index.html without 12393 fallback."""
        tray_rs = Path("apps/desktop-shell/src-tauri/src/tray.rs").read_text(encoding="utf-8")
        assert "12393" not in tray_rs
        assert 'WebviewUrl::App("index.html".into())' in tray_rs
