"""CPU-free provider for development and contract tests; not an LLM."""

import re
from collections.abc import AsyncIterator

from jat_api.models.contracts import GenerationRequest, GenerationResult, TokenEvent


class DeterministicProvider:
    name = "deterministic"

    def _response(self, request: GenerationRequest) -> str:
        user_messages = [message.content for message in request.messages if message.role == "user"]
        prompt = user_messages[-1].strip() if user_messages else ""
        return (
            f"JaT development provider received: {prompt}"
            if prompt
            else "JaT development provider ready."
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        text = self._response(request)
        return GenerationResult(
            text=text,
            model=request.model,
            input_tokens=sum(len(message.content.split()) for message in request.messages),
            output_tokens=len(text.split()),
            finish_reason="stop",
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[TokenEvent]:
        for index, word in enumerate(re.findall(r"\S+\s*", self._response(request))):
            yield TokenEvent(text=word, index=index)
