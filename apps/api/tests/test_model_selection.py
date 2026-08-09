"""Unit tests for per-conversation model selection and the system-prompt fallback.

Covers:
- ``UpdateConversationRequest`` accepts a model change (and title-only stays valid).
- ``effective_system_prompt`` prefers the user prompt and falls back to the operator default.
- ``list_ollama_models`` parses the Ollama ``/api/tags`` response (via an injected transport).
"""

from __future__ import annotations

import json

import httpx
import pytest

from jat_api.chat import effective_system_prompt
from jat_api.conversations import UpdateConversationRequest
from jat_api.models.providers.ollama import list_ollama_models

# --------------------------------------------------------------------------- system prompt fallback


@pytest.mark.parametrize(
    ("user_prompt", "default_prompt", "expected"),
    [
        ("Be concise.", "Operator default", "Be concise."),
        ("", "Operator default", "Operator default"),
        (None, "Operator default", "Operator default"),
        ("   ", "Operator default", "Operator default"),
        ("", "", ""),
    ],
)
def test_effective_system_prompt_prefers_user_then_operator(
    user_prompt: str | None, default_prompt: str, expected: str
) -> None:
    assert effective_system_prompt(user_prompt or "", default_prompt) == expected


def test_effective_system_prompt_strips_whitespace() -> None:
    assert effective_system_prompt("  stay brief  ", "") == "stay brief"
    assert effective_system_prompt("", "  operator baseline  ") == "operator baseline"


# --- conversation model patch


def test_update_conversation_request_accepts_model_only() -> None:
    payload = UpdateConversationRequest(model="llama3.1")

    assert payload.model == "llama3.1"
    assert payload.title is None


def test_update_conversation_request_accepts_title_only() -> None:
    payload = UpdateConversationRequest(title="Renamed chat")

    assert payload.title == "Renamed chat"
    assert payload.model is None


def test_update_conversation_request_rejects_blank_model() -> None:
    with pytest.raises(ValueError):
        UpdateConversationRequest(model="")


# --------------------------------------------------------------------------- Ollama model discovery


def _tags_payload(names: list[str]) -> bytes:
    return json.dumps({"models": [{"name": name} for name in names]}).encode()


async def test_list_ollama_models_returns_installed_names() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=_tags_payload(["llama3.1", "qwen2.5"]))
    )

    names = await list_ollama_models("http://localhost:11434/", transport=transport)

    assert names == ["llama3.1", "qwen2.5"]
    assert isinstance(names, list)


async def test_list_ollama_models_is_empty_when_no_models() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'{"models": []}'))

    assert await list_ollama_models("http://localhost:11434", transport=transport) == []


async def test_list_ollama_models_tolerates_malformed_entries() -> None:
    body = b'{"models": [{"name": "llama3.1"}, {"other": "x"}, {"name": "mistral"}]}'
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))

    assert await list_ollama_models("http://localhost:11434", transport=transport) == [
        "llama3.1",
        "mistral",
    ]


async def test_list_ollama_models_surfaces_server_errors() -> None:
    # Callers are expected to catch; the function itself must not swallow failures.
    transport = httpx.MockTransport(lambda request: httpx.Response(503, content=b"busy"))

    with pytest.raises(httpx.HTTPStatusError):
        await list_ollama_models("http://localhost:11434", transport=transport)
