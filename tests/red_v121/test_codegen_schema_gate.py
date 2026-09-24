"""The codegen chain must fail closed on a drifted contract, before writing."""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from lva.contracts import codegen  # noqa: E402


def test_expected_schema_sha256_is_pinned():
    assert codegen.EXPECTED_SCHEMA_SHA256, "the contract digest must be pinned"
    assert len(codegen.EXPECTED_SCHEMA_SHA256) == 64


def test_the_pin_matches_the_current_contract():
    from lva.contracts.normalize import canonical_sha256

    actual = canonical_sha256(codegen.generate_json_schema())
    assert actual == codegen.EXPECTED_SCHEMA_SHA256, (
        "the pinned digest no longer matches the contract; re-pin on purpose "
        "with `python -m lva.contracts.codegen --print-schema-sha`"
    )


def test_normalize_is_called_with_the_expected_sha256(monkeypatch):
    seen = {}
    real_normalize = codegen.normalize

    def spy(schema, expected_sha256=None):
        seen["expected"] = expected_sha256
        return real_normalize(schema, expected_sha256=expected_sha256)

    monkeypatch.setattr(codegen, "normalize", spy)
    codegen.generate_normalized_schema()
    assert seen.get("expected") == codegen.EXPECTED_SCHEMA_SHA256, (
        "generate_normalized_schema must pass the pinned digest to normalize()"
    )


def test_a_wrong_pin_fails_before_any_artifact_is_written(monkeypatch):
    targets = (codegen.SCHEMA_PATH, codegen.TS_PATH, codegen.RS_PATH)
    before = {p: p.read_bytes() for p in targets}

    monkeypatch.setattr(codegen, "EXPECTED_SCHEMA_SHA256", "0" * 64)
    with pytest.raises(codegen.CodegenError, match="SHA256 mismatch"):
        codegen.run_codegen()

    after = {p: p.read_bytes() for p in targets}
    assert before == after, "the gate must abort before writing any artifact"


def test_a_wrong_pin_fails_in_verify_mode_too(monkeypatch):
    monkeypatch.setattr(codegen, "EXPECTED_SCHEMA_SHA256", "0" * 64)
    with pytest.raises(codegen.CodegenError, match="SHA256 mismatch"):
        codegen.run_codegen(verify_only=True)