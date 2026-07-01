"""LLM factory, provider/usage introspection, and the shared per-role caller."""
import json
import logging
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from ai.orchestrator._models import LLMRoleResult
from core.config import settings

logger = logging.getLogger(__name__)


# ── LLM factory ───────────────────────────────────────────────────────────────

def _build_llm(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseChatModel:
    """Build a LangChain chat model from provider config or env-var settings."""
    resolved_provider = provider or settings.llm_provider

    if resolved_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "gpt-4o",
            api_key=api_key or settings.openai_api_key,
            temperature=0,
        )

    if resolved_provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model or settings.gemini_model,
            google_api_key=api_key or settings.gemini_api_key,
            temperature=0,
        )

    if resolved_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or "claude-sonnet-4-6",
            api_key=api_key or settings.anthropic_api_key,
            temperature=0,
        )

    if resolved_provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or settings.openrouter_model,
            api_key=api_key or settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=0,
        )

    if resolved_provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model or settings.ollama_model,
            base_url=api_key or settings.ollama_base_url,
            temperature=0,
        )

    raise ValueError(f"Unknown llm_provider: {resolved_provider!r}")


def _provider_from_llm(llm: BaseChatModel) -> str:
    """Derive short provider name from LangChain model class."""
    # Check for openrouter first — uses ChatOpenAI with a custom base_url
    base_url = str(getattr(llm, "openai_api_base", "") or "")
    if "openrouter" in base_url:
        return "openrouter"
    mod = type(llm).__module__
    if "openai" in mod:
        return "openai"
    if "google" in mod or "gemini" in mod:
        return "google"
    if "anthropic" in mod:
        return "anthropic"
    if "ollama" in mod:
        return "ollama"
    return "unknown"


def _model_name_from_llm(llm: BaseChatModel) -> str:
    """Extract model name string from LangChain model instance."""
    return getattr(llm, "model_name", None) or getattr(llm, "model", None) or "unknown"


def _extract_tokens(ai_msg: Any, provider: str) -> tuple[int | None, int | None, int | None]:
    """Extract (input_tokens, output_tokens, total_tokens) from LangChain AIMessage.

    Tries the standardized LangChain v0.2+ usage_metadata dict first (works across all
    providers), then falls back to provider-specific response_metadata fields.
    """
    try:
        # ── Standard LangChain v0.2+ path ─────────────────────────────────────
        # AIMessage.usage_metadata is a dict: {input_tokens, output_tokens, total_tokens}
        meta = getattr(ai_msg, "usage_metadata", None)
        if isinstance(meta, dict) and "input_tokens" in meta:
            inp = meta.get("input_tokens")
            out = meta.get("output_tokens")
            total = meta.get("total_tokens") or (
                (inp or 0) + (out or 0) if inp is not None and out is not None else None
            )
            return inp, out, total

        # ── Provider-specific fallbacks ────────────────────────────────────────
        if provider == "openai":
            usage = ai_msg.response_metadata.get("token_usage", {})
            inp = usage.get("prompt_tokens")
            out = usage.get("completion_tokens")
            total = usage.get("total_tokens")
            return inp, out, total

        if provider == "anthropic":
            usage = ai_msg.response_metadata.get("usage", {})
            inp = usage.get("input_tokens")
            out = usage.get("output_tokens")
            total = (inp or 0) + (out or 0) if inp is not None and out is not None else None
            return inp, out, total

        if provider == "google":
            # Older langchain-google-genai: usage data nested in response_metadata
            rm = getattr(ai_msg, "response_metadata", {}) or {}
            usage = rm.get("usage_metadata") or rm.get("usageMetadata") or {}
            if isinstance(usage, dict):
                inp = usage.get("prompt_token_count") or usage.get("promptTokenCount")
                out = usage.get("candidates_token_count") or usage.get("candidatesTokenCount")
                total = usage.get("total_token_count") or usage.get("totalTokenCount")
                return inp, out, total

    except Exception as exc:
        logger.debug("Could not extract token usage: %s", exc)
    return None, None, None


def log_llm_usage(ai_msg: Any, llm: BaseChatModel, caller: str) -> None:
    """Log token usage and estimated cost for any LLM call site outside orchestrator."""
    from core.llm_pricing import compute_cost
    provider = _provider_from_llm(llm)
    model = _model_name_from_llm(llm)
    inp, out, total = _extract_tokens(ai_msg, provider)
    cost = compute_cost(model, inp or 0, out or 0) if inp is not None or out is not None else None
    cost_str = f"${cost:.6f}" if cost is not None else "n/a"
    logger.info(
        "LLM caller=%s provider=%s model=%s input=%s output=%s total=%s cost=%s",
        caller, provider, model, inp, out, total, cost_str,
    )


# ── Per-role LLM caller ────────────────────────────────────────────────────────

async def _call_llm_for_role(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    role: str,
) -> LLMRoleResult:
    """Invoke an LLM directly (not via chain) and return result with token usage."""
    provider = _provider_from_llm(llm)
    model = _model_name_from_llm(llm)
    t0 = time.monotonic()

    ai_msg = await llm.ainvoke(messages)
    duration_ms = int((time.monotonic() - t0) * 1000)

    if isinstance(ai_msg.content, str):
        raw_text = ai_msg.content
    elif isinstance(ai_msg.content, list):
        # Anthropic Claude returns a list of content blocks: [{'type': 'text', 'text': '...'}]
        raw_text = "\n".join(
            block["text"] if isinstance(block, dict) and "text" in block else str(block)
            for block in ai_msg.content
        )
    else:
        raw_text = str(ai_msg.content)
    inp, out, total = _extract_tokens(ai_msg, provider)

    # Parse JSON from the text response
    try:
        # Strip markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        content = json.loads(text)
    except Exception:
        content = raw_text

    prompt_payload = []
    for m in messages:
        if isinstance(m.content, list):
            content_parts = []
            for item in m.content:
                if isinstance(item, dict) and item.get("type") == "text":
                    content_parts.append(str(item.get("text")))
                elif isinstance(item, dict) and item.get("type") == "image_url":
                    content_parts.append("[IMAGE BASE64 OMITTED]")
                else:
                    content_parts.append(str(item))
            content_str = "\n".join(content_parts)
        else:
            content_str = str(m.content)

        role_type = type(m).__name__.replace("Message", "").lower()
        prompt_payload.append({
            "role": role_type,
            "content": content_str
        })

    from core.llm_pricing import compute_cost
    cost = compute_cost(model, inp or 0, out or 0) if inp is not None or out is not None else None
    cost_str = f"${cost:.6f}" if cost is not None else "n/a"
    logger.info(
        "LLM role=%s provider=%s model=%s input=%s output=%s total=%s cost=%s duration=%dms",
        role, provider, model, inp, out, total, cost_str, duration_ms,
    )
    return LLMRoleResult(
        content=content,
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        model=model,
        provider=provider,
        duration_ms=duration_ms,
        raw_text=raw_text,
        prompt=prompt_payload,
    )

