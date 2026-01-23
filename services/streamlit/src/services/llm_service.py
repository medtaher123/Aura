"""LLM service module.

This project use AWS Bedrock (Converse API) and is designed to be imported
without immediately requiring AWS credentials (network calls only happen when
`get_chat_llm()` is invoked).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Optional

from src.core.config import DEFAULT_LLM_TEMPERATURE


DEFAULT_BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "arn:aws:bedrock:eu-west-3:637423200916:inference-profile/eu.anthropic.claude-3-7-sonnet-20250219-v1:0",
)
DEFAULT_BEDROCK_REGION = os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION") or "eu-west-3"


def _infer_bedrock_provider(model_id: str) -> Optional[str]:
    """Best-effort provider inference for Bedrock.

    `langchain_aws.ChatBedrockConverse` requires `provider` when `model_id` is an ARN.
    For example, Meta Llama inference profiles look like:
      arn:aws:bedrock:...:inference-profile/eu.meta.llama3-2-1b-instruct-v1:0
    """

    if not isinstance(model_id, str) or not model_id.strip():
        return None

    s = model_id.strip()
    # If ARN, the interesting part is usually after the last '/'
    if s.startswith("arn:") and "/" in s:
        s = s.rsplit("/", 1)[-1]

    lower = s.lower()
    if ".meta." in lower or lower.startswith("meta.") or lower.startswith("eu.meta."):
        return "meta"
    if "anthropic" in lower:
        return "anthropic"
    if "amazon" in lower or lower.startswith("amazon."):
        return "amazon"
    if "cohere" in lower:
        return "cohere"
    if "mistral" in lower:
        return "mistral"

    return None


def get_chat_llm(
    model_id: Optional[str] = None,
    *,
    region: Optional[str] = None,
    temperature: Optional[float] = 0.1,
    max_tokens: Optional[int] = None,
    top_p: Optional[float] = 0.3,
) -> Any:
    """Return a LangChain chat model backed by AWS Bedrock.

    Configure via env vars:
    - `BEDROCK_MODEL_ID` (defaults to the EU Meta Llama 3.2 1B Instruct inference profile)
    - `BEDROCK_REGION` or `AWS_REGION` (defaults to eu-west-3)
    - `BEDROCK_MAX_TOKENS`, `BEDROCK_TOP_P`
    """

    # Lazy imports so test imports don't require Bedrock connectivity.
    import boto3

    try:
        from langchain_aws import ChatBedrockConverse as _ChatBedrock
    except Exception:  # pragma: no cover
        # Fallback for older langchain-aws versions.
        from langchain_aws import ChatBedrock as _ChatBedrock  # type: ignore

    model_id = model_id or DEFAULT_BEDROCK_MODEL_ID
    region = region or DEFAULT_BEDROCK_REGION

    if temperature is None:
        temperature = float(DEFAULT_LLM_TEMPERATURE)
    if max_tokens is None:
        max_tokens = int(os.getenv("BEDROCK_MAX_TOKENS", "1024"))
    if top_p is None:
        top_p = float(os.getenv("BEDROCK_TOP_P", "0.9"))

    client = boto3.client("bedrock-runtime", region_name=region)

    # Support multiple langchain-aws versions by only passing supported fields.
    fields = getattr(_ChatBedrock, "model_fields", {}) or {}
    kwargs: dict[str, Any] = {}

    if "client" in fields:
        kwargs["client"] = client
    elif "region_name" in fields:
        kwargs["region_name"] = region

    if "model_id" in fields:
        kwargs["model_id"] = model_id
    elif "model" in fields:
        kwargs["model"] = model_id

    provider = _infer_bedrock_provider(model_id)
    if "provider" in fields and provider is not None:
        kwargs["provider"] = provider

    if "temperature" in fields:
        kwargs["temperature"] = temperature
    if "max_tokens" in fields:
        kwargs["max_tokens"] = max_tokens
    # Anthropic models on Bedrock reject specifying both temperature and top_p.
    if "top_p" in fields and provider != "anthropic":
        kwargs["top_p"] = top_p

    # Some versions use `model_kwargs` for provider-specific parameters.
    if "model_kwargs" in fields and "max_tokens" not in kwargs:
        model_kwargs = {
            "temperature": temperature,
            # Meta Llama on Bedrock typically expects `max_gen_len`.
            "max_gen_len": max_tokens,
            # Keep a common alias too.
            "max_tokens": max_tokens,
        }
        if provider != "anthropic":
            model_kwargs["top_p"] = top_p
        kwargs["model_kwargs"] = model_kwargs

    return _ChatBedrock(**kwargs)


def get_llm(*args, **kwargs):
    """Backward-compatible alias used by older call sites."""
    return get_chat_llm(*args, **kwargs)
