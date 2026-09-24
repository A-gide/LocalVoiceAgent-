"""RED: PR-015 remove direct llama lifecycle and scanner (R19).

Frozen basis (L1280-1288):

* `Current -> target`: Rust/scripts scanning, spawning, killing or switching
  llama-server -> **only send Hub intents to Core**.
* `Files/new`: modify `process_manager.rs` / `lib.rs` / `tray.rs` /
  `services.default.json` and the related scripts; delete functions confirmed
  unused.
* `Steps`: command compatibility mapping; remove the GGUF scanner, 1234/LM paths,
  `unload_vram`/`cold_start`; static kill allowlist.
* `Acceptance`: I16/I21; **grep finds no LM Studio / direct llama lifecycle**;
  Rust/TS carry no Hub management client; the Hub and its children survive an LVA
  quit; a real Hub switch passes.

Scope note: the real-Hub half of the acceptance line ("真实 Hub switch 通过" and
"LVA quit 后 Hub/children 存活") needs a live Hub and is not reachable here; the
static half -- no direct lifecycle surface, no LM path, no 1234 default -- is what
this file asserts.
"""
from __future__ import annotations

import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

LVA = REPO_ROOT / "src" / "lva"
TAURI_SRC = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src"
LIB_RS = TAURI_SRC / "lib.rs"
CONFIG_PY = LVA / "config.py"

# The direct lifecycle surface PR-015 removes (plan L1285).
DIRECT_LIFECYCLE = (
    "scan_models",
    "refresh_models",
    "switch_llm_model",
    "unload_vram",
    "cold_start_llm",
)


def test_no_direct_model_lifecycle_command_is_exposed():
    """Plan L1285: remove the GGUF scanner and unload_vram/cold_start."""
    src = read_text(LIB_RS)
    present = [name for name in DIRECT_LIFECYCLE if f"fn {name}(" in src]
    assert not present, (
        "PR-015: the Tauri shell still owns a direct model lifecycle surface "
        f"({present}); model runtime must be reached only via Core -> Hub"
    )


def test_no_direct_model_lifecycle_command_is_registered():
    """Removing the handler but leaving it in `generate_handler!` would not build,"
    "but removing it from the handler while a stale wrapper remains is the subtler
    "half of the same change.
    """
    src = read_text(LIB_RS)
    handler = src[src.index("generate_handler![") :]
    handler = handler[: handler.index("]")]
    present = [name for name in DIRECT_LIFECYCLE if name in handler]
    assert not present, (
        f"PR-015: these commands are still registered with the shell: {present}"
    )


def test_no_legacy_1234_default_anywhere_in_config():
    """Plan L1285: remove the 1234 / LM paths; the default targets the Hub."""
    cfg = read_text(CONFIG_PY)
    assert "127.0.0.1:1234" not in cfg, (
        "PR-015: the 1234 / LM Studio default endpoint must be removed"
    )
    assert "1234" not in cfg, "PR-015: no 1234 default may remain in config.py"


def test_the_default_llm_endpoint_targets_the_hub():
    """The replacement must actually point at the Hub inference face."""
    cfg = read_text(CONFIG_PY)
    assert re.search(r"LLM_BASE_URL\s*=", cfg), "LLM_BASE_URL must still exist"
    assert "8080" in cfg or "HUB" in cfg.upper(), (
        "the default LLM endpoint must target the Hub (plan L1263: Hub /v1)"
    )


def test_no_lm_studio_reference_in_rust_or_scripts():
    """Plan L1287 acceptance: grep finds no LM Studio / direct llama lifecycle."""
    offenders: list[str] = []
    roots = [TAURI_SRC, REPO_ROOT / "scripts"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".rs", ".ps1", ".py"}:
                continue
            if "target" in path.parts:
                continue
            text = read_text(path)
            # `llama.cpp-hub` is the *Hub* and stays; a bare llama-server path or
            # an LM Studio install path is what must go.
            for pattern in ("lmstudio", "LM Studio", "llama-server.exe", "lm_studio"):
                if pattern.lower() in text.lower():
                    offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()} -> {pattern}")
    assert not offenders, (
        f"PR-015: direct llama/LM Studio references must be gone; found {offenders}"
    )


def test_services_default_has_no_direct_llama_entry():
    """`services.default.json` must describe LVA services, not a llama backend."""
    import json

    path = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "services.default.json"
    data = json.loads(read_text(path))
    for name, entry in data.get("services", {}).items():
        blob = json.dumps(entry).lower()
        assert "llama-server" not in blob, (
            f"services.default.json still spawns a direct llama backend under `{name}`"
        )


def test_removed_commands_do_not_linger_as_wrappers():
    """Plan L1284: delete functions confirmed unused, not just unregister them."""
    src = read_text(LIB_RS)
    for name in DIRECT_LIFECYCLE:
        assert not re.search(rf"fn\s+{name}\s*\(", src), (
            f"`{name}` must be deleted, not left as an uncalled wrapper"
        )

