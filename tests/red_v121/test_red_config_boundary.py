"""RED: v1.2.1 PR-003 runtime configuration boundary and PR-004 secret DTO (R11).

Frozen rule:

* PR-003 (L1158-1166): user configuration tracked in the repo -> LocalAppData
  runtime config + repo examples.  Steps: first-run copy/migrate; no sensitive
  fields in examples; back up the original runtime file; emit a redacted
  migration report.  Acceptance: clean-machine defaults, legacy copy, paths with
  no username/drive letter, and a repo scan free of runtime ciphertext.
* PR-004 (L1168-1176): `get_settings` could return a secret -> public DTO +
  write-only secret commands.  `get_public_settings` returns only a configured
  flag plus `settings_revision`; `set_secret`/`clear_secret`/`test_provider` are
  separated; write commands use the settings aggregate precondition; logs are
  uniformly redacted.  Acceptance: no secret/ciphertext in IPC serialization;
  concurrent settings writes can return `STALE_REVISION` while heartbeat does not
  affect the settings revision; log/diagnostic export carries no key.

These assertions are structural (they read source and JSON structure, never a
secret value).  The behavioural half -- a real first-run migration, a real
concurrent write returning `STALE_REVISION` -- belongs to the Rust unit tests
beside the code, because only there can it execute.
"""
from __future__ import annotations

import json
import re

import pytest

from harness import REPO_ROOT, read_text

pytestmark = pytest.mark.red_v121

SRC = REPO_ROOT / "apps" / "desktop-shell" / "src-tauri" / "src"
PATHS_RS = SRC / "paths.rs"
SETTINGS_RS = SRC / "settings.rs"
SETTINGS_EXAMPLE = REPO_ROOT / "settings.example.json"
SERVICES_EXAMPLE = REPO_ROOT / "services.example.json"
GITIGNORE = REPO_ROOT / ".gitignore"

# Runtime files that must never be tracked once PR-003 lands.
RUNTIME_CONFIG_FILES = ("settings.json", "services.json", "user_profile.json")


def _subprocess_git(*args: str) -> tuple[int, str]:
    import subprocess

    proc = subprocess.run(
        ["git", "-c", "safe.directory=E:/AI/LocalVoiceAgent", "-C",
         str(REPO_ROOT).replace("\\", "/"), *args],
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout


# ------------------------------------------------------------ PR-003 boundary
def test_runtime_config_files_are_not_tracked_by_git():
    """PR-003: user configuration must not be tracked in the repo.

    A `.gitignore` entry alone is inert for a file that is already tracked, so
    this asserts the real property (not in the index) rather than the intent.
    """
    still_tracked: list[str] = []
    for name in RUNTIME_CONFIG_FILES:
        code, _ = _subprocess_git("ls-files", "--error-unmatch", name)
        if code == 0:
            still_tracked.append(name)
    assert not still_tracked, (
        "PR-003: these runtime config files are still tracked in git, so the "
        f".gitignore rule is inert: {still_tracked}. They must be untracked "
        "(git rm --cached) and migrated to the runtime config root."
    )


def test_gitignore_covers_the_runtime_config_files():
    src = read_text(GITIGNORE)
    missing = [name for name in RUNTIME_CONFIG_FILES if name not in src]
    assert not missing, f"PR-003: .gitignore must cover {missing}"


def test_runtime_config_root_is_not_the_repository():
    """PR-003: runtime config lives under LocalAppData, not in the checkout."""
    src = read_text(PATHS_RS)
    assert re.search(r"LocalAppData|LOCALAPPDATA|local_app_data", src, re.I), (
        "PR-003: get_app_dir() resolves only LVA_ROOT / LVA_CONFIG_DIR / portable "
        "mode; the frozen target is a %LOCALAPPDATA% runtime config root"
    )


def test_paths_have_no_username_or_drive_letter_in_the_examples():
    """PR-003 acceptance: paths carry no username and no drive letter."""
    for example in (SETTINGS_EXAMPLE, SERVICES_EXAMPLE):
        raw = read_text(example)
        assert not re.search(r"[A-Za-z]:\\\\", raw), (
            f"PR-003: {example.name} carries a drive-letter path"
        )
        assert "Users\\\\" not in raw and "/Users/" not in raw, (
            f"PR-003: {example.name} carries a username-bearing path"
        )


def test_examples_carry_no_secret_material():
    """PR-003: sensitive fields must not be populated in the examples."""
    settings = json.loads(read_text(SETTINGS_EXAMPLE))
    for key, value in settings.items():
        if "api_key" in key:
            assert value == "", (
                f"PR-003: settings.example.json must leave `{key}` empty, got a value"
            )


def test_a_migration_helper_exists():
    """PR-003 Steps: first-run copy/migrate, backup, redacted migration report."""
    src = read_text(SETTINGS_RS) + read_text(PATHS_RS)
    assert re.search(r"fn\s+migrate", src), (
        "PR-003: no migration helper found; the frozen step is 'first-run "
        "copy/migrate + back up the original runtime file + redacted report'"
    )


# ------------------------------------------------------------- PR-004 secrets
def test_public_dto_exposes_a_settings_revision():
    """PR-004 (L1173) + plan L397: the public DTO carries `settings_revision`."""
    src = read_text(SETTINGS_RS)
    block = re.search(r"pub struct PublicAppSettings \{(.*?)\n\}", src, re.S)
    assert block, "PublicAppSettings must be declared"
    assert "settings_revision" in block.group(1), (
        "PR-004: the public settings DTO must expose `settings_revision` so a "
        "concurrent write can be rejected as STALE_REVISION"
    )


def test_public_dto_carries_no_secret_material():
    """PR-004 acceptance: no secret/ciphertext in IPC serialization."""
    src = read_text(SETTINGS_RS)
    block = re.search(r"pub struct PublicAppSettings \{(.*?)\n\}", src, re.S)
    assert block, "PublicAppSettings must be declared"
    body = block.group(1)
    for leak in ("_enc", "api_key:"):
        assert leak not in body, (
            f"PR-004: PublicAppSettings must not carry `{leak}`; only a configured "
            "flag may cross the boundary"
        )


def test_secret_commands_are_separated_from_general_settings_write():
    """PR-004 Steps: `set_secret`/`clear_secret` are separate write-only ops.

    `test_provider` is deliberately *not* asserted here: the frozen text lists it
    alongside the secret commands but it is a provider probe rather than a secret
    mutation, so requiring it in the secret path would over-specify the slice.
    """
    src = read_text(SETTINGS_RS)
    for fn in ("set_secret", "clear_secret"):
        assert f"fn {fn}" in src, (
            f"PR-004: `{fn}` must exist as its own operation rather than being "
            "folded into the general settings write"
        )
    # A general settings write must not be able to inject a secret.
    block = re.search(r"pub fn update_settings\b(.*?)\n    \}", src, re.S)
    assert block, "update_settings must exist"
    assert "api_key" not in block.group(1) or "is_empty" in block.group(1), (
        "PR-004: the general settings write must not be a path for setting a secret"
    )


def test_secrets_are_encrypted_on_disk_and_never_plaintext():
    """PR-004: the disk DTO holds ciphertext; the runtime file proves it."""
    src = read_text(SETTINGS_RS)
    assert "dpapi_encrypt" in src, (
        "PR-004: secrets must be encrypted before they reach disk"
    )
    runtime = REPO_ROOT / "settings.json"
    if runtime.is_file():
        data = json.loads(read_text(runtime))
        plaintext_keys = [k for k in data if k.endswith("api_key")]
        assert not plaintext_keys, (
            "PR-004: the runtime settings file carries plaintext key fields: "
            f"{plaintext_keys}"
        )


def test_repo_scan_finds_no_runtime_ciphertext():
    """PR-003 acceptance: repo scan free of runtime ciphertext.

    Note this asserts the *ciphertext* is absent from tracked content, not that the
    runtime file is deleted.  PR-003's rollback note explicitly requires keeping
    the old file importable for one release and never auto-deleting a user's own
    file, so file existence on disk is not the property under test.
    """
    ciphertext_fields: list[str] = []
    for name in RUNTIME_CONFIG_FILES:
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        code, _ = _subprocess_git("ls-files", "--error-unmatch", name)
        if code != 0:
            continue  # untracked: not part of a repo scan
        try:
            data = json.loads(read_text(path))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            ciphertext_fields.extend(
                f"{name}:{k}" for k in data if k.endswith("_enc")
            )
    assert not ciphertext_fields, (
        "PR-003: tracked runtime configuration still carries ciphertext fields: "
        f"{ciphertext_fields}"
    )
