"""Model router + cache + cost ledger.

Two tiers:
  cheap  — bulk work: classifying announcements, one-liners, extraction from filings.
  strong — reasoning: narrative vs numbers, bull/bear, "why this person".

Every call is keyed by sha256(provider, model, system, prompt, schema). An identical request
is served from `llm_calls` for free, and every row records tokens and dollars, so the app
can show exactly what it spent.
"""

import hashlib
import json
import logging
import time
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import LLMCall

log = logging.getLogger(__name__)
Tier = Literal["cheap", "strong"]

# USD per 1M tokens (input, output). Unknown models are logged with cost None.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


class LLMUnavailable(RuntimeError):
    """No API key configured / provider down. Callers fall back to rules."""


def _route(tier: Tier) -> tuple[str, str]:
    s = get_settings()
    return (
        (s.llm_cheap_provider, s.llm_cheap_model)
        if tier == "cheap"
        else (s.llm_strong_provider, s.llm_strong_model)
    )


def is_available(tier: Tier = "cheap") -> bool:
    s = get_settings()
    provider, _ = _route(tier)
    return bool(s.anthropic_api_key if provider == "anthropic" else s.gemini_api_key)


def _call_anthropic(model: str, system: str, prompt: str, schema: dict | None,
                    max_tokens: int, effort: str) -> tuple[str, int, int]:
    import anthropic

    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    kwargs: dict = {}
    if schema is not None:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema},
                                   "effort": effort}
    else:
        kwargs["output_config"] = {"effort": effort}
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable(str(e)) from e
    except anthropic.AuthenticationError as e:
        raise LLMUnavailable("Anthropic API key rejected") from e
    if resp.stop_reason == "refusal":
        raise LLMUnavailable("model declined the request")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return text, resp.usage.input_tokens, resp.usage.output_tokens


def _call_gemini(model: str, system: str, prompt: str, schema: dict | None,
                 max_tokens: int, effort: str) -> tuple[str, int, int]:
    key = get_settings().gemini_api_key
    body: dict = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if schema is not None:
        body["generationConfig"] |= {"responseMimeType": "application/json",
                                     "responseJsonSchema": schema}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        r = httpx.post(url, json=body, headers={"x-goog-api-key": key}, timeout=120)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise LLMUnavailable(str(e)) from e
    data = r.json()
    text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    usage = data.get("usageMetadata", {})
    return text, usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)


def complete(
    db: Session,
    *,
    task: str,
    system: str,
    prompt: str,
    schema: dict | None = None,
    tier: Tier = "cheap",
    max_tokens: int = 4096,
    effort: str = "low",
) -> str | dict:
    """Run one model call (or serve it from cache). Returns parsed JSON when `schema` is set."""
    if not is_available(tier):
        raise LLMUnavailable(f"no API key for the {tier} tier")
    provider, model = _route(tier)
    key = hashlib.sha256(
        json.dumps([provider, model, system, prompt, schema, effort], sort_keys=True).encode()
    ).hexdigest()

    if get_settings().llm_cache_enabled:
        hit = db.scalar(select(LLMCall).where(LLMCall.cache_key == key))
        if hit is not None:
            hit.hits += 1
            db.flush()
            return json.loads(hit.response) if schema is not None else hit.response

    call = _call_anthropic if provider == "anthropic" else _call_gemini
    t0 = time.perf_counter()
    text, tin, tout = call(model, system, prompt, schema, max_tokens, effort)
    price = PRICES.get(model)
    db.add(LLMCall(
        cache_key=key, task=task, provider=provider, model=model, response=text,
        input_tokens=tin, output_tokens=tout,
        cost_usd=(tin * price[0] + tout * price[1]) / 1e6 if price else None,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    ))
    db.flush()
    return json.loads(text) if schema is not None else text
