"""Local LLM client (OpenAI-compatible, loopback only).

Two behaviours matter for a live assistant and both are handled here:

* fast/deep routing - a normal chat turn must not pay for a long reasoning
  pass.  The client asks the server to skip thinking (`enable_thinking=false`)
  and, for templates that ignore that flag, also stops the model at the first
  token of the answer field.
* cancellation - barge-in needs `stream()` to be abandonable mid-generation.
  The generator is closed by the caller and the HTTP stream is dropped.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Iterable, Iterator

import httpx

from . import config as C


class LLMError(RuntimeError):
    pass


@dataclass
class ChatStats:
    ttft_ms: float = 0.0
    total_ms: float = 0.0
    chars: int = 0
    tokens: int = 0
    model: str = ""
    mode: str = "fast"

    @property
    def chars_per_s(self) -> float:
        return self.chars / (self.total_ms / 1000.0) if self.total_ms else 0.0


@dataclass
class StreamResult:
    text: str = ""
    stats: ChatStats = field(default_factory=ChatStats)
    cancelled: bool = False


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if C.LLM_API_KEY:
        h["Authorization"] = f"Bearer {C.LLM_API_KEY}"
    return h


def list_models(base_url: str | None = None, timeout: float = 10.0) -> list[dict]:
    url = (base_url or C.LLM_BASE_URL).rstrip("/") + "/models"
    try:
        r = httpx.get(url, timeout=timeout, headers=_headers())
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"cannot reach LLM server at {url}: {e}") from e
    data = r.json()
    return data.get("data", data.get("models", []))


def health(base_url: str | None = None) -> dict:
    t0 = time.perf_counter()
    try:
        models = list_models(base_url)
    except LLMError as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        "models": [m.get("id") or m.get("name") for m in models],
    }


def _body(messages: list[dict], model: str, mode: str, stream: bool,
          max_tokens: int, temperature: float, extra: dict | None = None) -> dict:
    body: dict = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if mode == "fast":
        # llama.cpp accepts this and passes it to the chat template; templates
        # without a thinking switch simply ignore the key.
        body["chat_template_kwargs"] = {"enable_thinking": False}
    if extra:
        body.update(extra)
    return body


def stream_events(messages: list[dict], model: str | None = None, mode: str = "fast",
                  max_tokens: int | None = None, temperature: float = 0.7,
                  base_url: str | None = None, stop=None,
                  extra: dict | None = None) -> Iterator[dict]:
    """Yield `{"type": "content"|"reasoning", "text": ...}` deltas.

    The models on this machine separate their thinking pass into
    `reasoning_content`.  A live turn must never speak that channel, but it is
    useful for the UI "thinking" state, so both are surfaced here and callers
    choose.  Close the generator to cancel generation.
    """
    url = (base_url or C.LLM_BASE_URL).rstrip("/") + "/chat/completions"
    budget = max_tokens if max_tokens is not None else (
        C.LLM_MAX_TOKENS if mode == "fast" else C.LLM_DEEP_MAX_TOKENS)
    body = _body(messages, model or C.LLM_MODEL, mode, True, budget, temperature, extra)
    if stop:
        body["stop"] = stop
    with httpx.stream("POST", url, json=body, timeout=C.LLM_TIMEOUT,
                      headers=_headers()) as r:
        if r.status_code >= 400:
            detail = r.read().decode("utf-8", "replace")[:400]
            raise LLMError(f"LLM HTTP {r.status_code}: {detail}")
        for line in r.iter_lines():
            if not line:
                continue
            payload = line[5:].strip() if line.startswith("data:") else line.strip()
            if payload == "[DONE]":
                return
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for ch in obj.get("choices", []):
                delta = ch.get("delta") or {}
                if delta.get("content"):
                    yield {"type": "content", "text": delta["content"]}
                elif delta.get("reasoning_content"):
                    yield {"type": "reasoning", "text": delta["reasoning_content"]}


def stream(messages: list[dict], **kw) -> Iterator[str]:
    """Content-only convenience wrapper around `stream_events`."""
    want_reasoning = kw.pop("include_reasoning", False)
    for ev in stream_events(messages, **kw):
        if ev["type"] == "content" or want_reasoning:
            yield ev["text"]


def complete(messages: list[dict], **kw) -> StreamResult:
    """Non-streaming convenience wrapper."""
    kw.pop("stop", None)
    t0 = time.perf_counter()
    out = []
    for piece in stream(messages, **kw):
        out.append(piece)
    text = "".join(out)
    dt = (time.perf_counter() - t0) * 1000
    return StreamResult(text=text, stats=ChatStats(ttft_ms=dt, total_ms=dt, chars=len(text)))


def collect(gen: Iterable[str], stats: ChatStats) -> StreamResult:
    """Drain a stream (up to the first response) and record latency."""
    t0 = time.perf_counter()
    parts: list[str] = []
    ttft = 0.0
    try:
        for piece in gen:
            if not parts and piece:
                ttft = (time.perf_counter() - t0) * 1000
            parts.append(piece)
    except GeneratorExit:      # pragma: no cover - closed by caller
        pass
    finally:
        try:
            gen.close()        # type: ignore[attr-defined]
        except Exception:
            pass
    stats.ttft_ms = ttft
    stats.total_ms = (time.perf_counter() - t0) * 1000
    stats.chars = sum(len(p) for p in parts)
    return StreamResult(text="".join(parts), stats=stats)
