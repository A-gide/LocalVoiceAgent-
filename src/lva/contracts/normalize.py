"""Fail-closed schema normalization for the pinned Rust/TS codegen chain.

Pydantic emits several constructs that `typify 0.8.0` cannot lower directly:

* anonymous property schemas carry a `title` derived from the field name; two
  different models routinely produce the same title, and typify reuses the
  first-registered type without checking structural equivalence.  That reuse
  fails with `InvalidValue` on the whole schema.
* discriminated unions are emitted as `oneOf` + `$ref` branches; typify only
  produces a tagged enum when the branches are inlined AND the discriminator is
  in `required`.

This module performs exactly those two transformations and refuses everything
else.  It never mutates its input and never widens its own scope: an unexpected
shape raises `NormalizeError` so the generation chain stops instead of silently
producing a weaker contract.

Canonical `required`, `const`, `default` and `additionalProperties` are
preserved verbatim; the shared `$defs` map is never modified.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

__all__ = ["NormalizeError", "normalize", "canonical_sha256"]


class NormalizeError(RuntimeError):
    """Raised when the input schema contains a shape this normalizer refuses."""


# Only schemas reachable through `/properties/` are anonymous property schemas.
# Model-level titles (`/$defs/<Name>`) and the root title are preserved.
_PROPERTY_POINTER = re.compile(r"^\$defs/[^/]+/properties/")


def canonical_sha256(obj: Any) -> str:
    """Stable SHA256 over a canonical JSON encoding (key order independent)."""
    encoded = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _is_model_title(pointer: str) -> bool:
    return pointer == "" or re.fullmatch(r"/\$defs/[^/]+", pointer) is not None


def _is_property_derived(pointer: str) -> bool:
    return bool(_PROPERTY_POINTER.match(pointer.lstrip("/")))


def _resolve(root: Any, pointer: str) -> Any:
    node = root
    for segment in (s for s in pointer.split("/") if s):
        if isinstance(node, list):
            node = node[int(segment)]
        elif isinstance(node, dict):
            if segment not in node:
                raise NormalizeError(f"JSON Pointer does not resolve: {pointer!r}")
            node = node[segment]
        else:
            raise NormalizeError(f"JSON Pointer crosses a scalar: {pointer!r}")
    return node


def _collect_titles(node: Any, pointer: str, out: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        title = node.get("title")
        if isinstance(title, str):
            out.append((pointer, title))
        for key, value in node.items():
            _collect_titles(value, f"{pointer}/{key}", out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _collect_titles(value, f"{pointer}/{index}", out)


def _ref_name(ref: Any) -> str:
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        raise NormalizeError(f"expected a local $defs reference, got {ref!r}")
    return ref.split("/")[-1]


# --------------------------------------------------------------------------- #
# rule A -- title collision removal
# --------------------------------------------------------------------------- #
def _normalize_titles(schema: dict) -> tuple[dict, list[str]]:
    out = copy.deepcopy(schema)
    found: list[tuple[str, str]] = []
    _collect_titles(out, "", found)

    anonymous: dict[str, list[str]] = {}
    for pointer, title in found:
        if _is_model_title(pointer):
            continue
        if not _is_property_derived(pointer):
            raise NormalizeError(
                "title found outside a property-derived schema: "
                f"{pointer!r} (refusing to widen scope)"
            )
        anonymous.setdefault(title, []).append(pointer)

    changes: list[str] = []
    for title, pointers in sorted(anonymous.items()):
        if len(pointers) < 2:
            continue
        for pointer in pointers[1:]:
            node = _resolve(out, pointer)
            if not isinstance(node, dict) or node.get("title") != title:
                raise NormalizeError(f"title not where expected: {pointer!r}")
            del node["title"]
            changes.append(f"DROP-TITLE {pointer} (collided on {title!r})")
    return out, sorted(changes)


# --------------------------------------------------------------------------- #
# rule B -- discriminated union branch inlining
# --------------------------------------------------------------------------- #
def _inline_branch(schema: dict, defs: dict, branch: Any, prop: str,
                   mapping: dict | None, path: str, index: int) -> dict:
    if not isinstance(branch, dict) or set(branch) != {"$ref"}:
        raise NormalizeError(
            f"{path}: branch[{index}] must be a pure local $ref, got {sorted(branch)}"
        )
    name = _ref_name(branch["$ref"])
    if name not in defs:
        raise NormalizeError(f"{path}: branch[{index}] references missing $defs/{name}")

    target = defs[name]
    if not isinstance(target, dict) or target.get("type") != "object":
        raise NormalizeError(f"{path}: branch[{index}] target {name} is not an object")

    properties = target.get("properties", {})
    if prop not in properties:
        raise NormalizeError(
            f"{path}: branch[{index}] target {name} lacks discriminator {prop!r}"
        )
    if prop not in target.get("required", []):
        raise NormalizeError(
            f"{path}: branch[{index}] target {name} does not require {prop!r}"
        )

    spec = properties[prop]
    if "const" in spec:
        values = [spec["const"]]
    elif isinstance(spec.get("enum"), list) and len(spec["enum"]) == 1:
        values = spec["enum"]
    else:
        raise NormalizeError(
            f"{path}: branch[{index}] {name}.{prop} is not a single-value const/enum"
        )

    if mapping is not None:
        tag = values[0]
        if tag not in mapping:
            raise NormalizeError(f"{path}: discriminator mapping lacks tag {tag!r}")
        if mapping[tag] != branch["$ref"]:
            raise NormalizeError(
                f"{path}: mapping[{tag!r}]={mapping[tag]!r} != branch ref {branch['$ref']!r}"
            )
    return copy.deepcopy(target)


def _normalize_discriminated(schema: dict) -> tuple[dict, list[str]]:
    out = copy.deepcopy(schema)
    defs = out.get("$defs", {})
    changes: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "oneOf" in node and "discriminator" in node:
                discriminator = node["discriminator"]
                if not isinstance(discriminator, dict) or "propertyName" not in discriminator:
                    raise NormalizeError(f"{path}: discriminator has no propertyName")
                prop = discriminator["propertyName"]
                mapping = discriminator.get("mapping")
                branches = node["oneOf"]
                if not isinstance(branches, list) or not branches:
                    raise NormalizeError(f"{path}: oneOf is not a non-empty list")
                if mapping is not None:
                    if not isinstance(mapping, dict):
                        raise NormalizeError(f"{path}: discriminator mapping is not an object")
                    if len(mapping) != len(branches):
                        raise NormalizeError(
                            f"{path}: mapping has {len(mapping)} entries for "
                            f"{len(branches)} branches"
                        )
                node["oneOf"] = [
                    _inline_branch(out, defs, branch, prop, mapping, path, i)
                    for i, branch in enumerate(branches)
                ]
                changes.append(
                    f"INLINE-ONEOF {path} ({len(branches)} branches on {prop!r})"
                )
            for key, value in list(node.items()):
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")

    walk(out, "")

    if set(out.get("$defs", {})) != set(defs):
        raise NormalizeError("$defs key set changed during normalization")
    for name, original in schema.get("$defs", {}).items():
        rewritten = out["$defs"][name]
        for field in ("required", "additionalProperties"):
            if original.get(field) != rewritten.get(field):
                raise NormalizeError(f"$defs/{name}.{field} was modified")
    return out, sorted(changes)


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #
def normalize(schema: dict, expected_sha256: str | None = None) -> tuple[dict, list[str]]:
    """Return ``(normalized_schema, changes)`` for a Pydantic JSON Schema.

    When ``expected_sha256`` is given the input is verified first and a mismatch
    aborts before any result is produced, so a stale or substituted schema can
    never reach the generators.
    """
    if expected_sha256 is not None:
        actual = canonical_sha256(schema)
        if actual.lower() != expected_sha256.lower():
            raise NormalizeError(
                "input schema SHA256 mismatch: "
                f"expected {expected_sha256}, got {actual} "
                "(aborting before producing any output)"
            )

    titled, title_changes = _normalize_titles(schema)
    inlined, inline_changes = _normalize_discriminated(titled)
    return inlined, sorted(title_changes + inline_changes)