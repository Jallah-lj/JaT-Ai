"""Provider-neutral LLM request and streaming contracts for JaT orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ChatMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True)
class GenerationRequest:
    messages: list[ChatMessage]
    model: str
    max_tokens: int
    temperature: float
    context_length: int
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TokenEvent:
    text: str
    index: int


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    finish_reason: Literal["stop", "length", "error"]


class LLMProvider(Protocol):
    """Stable boundary allowing JaT to replace model infrastructure safely."""

    name: str

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[TokenEvent]: ...
