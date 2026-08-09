"""Controlled slow provider used only to exercise streaming cancellation in tests."""

import asyncio
from collections.abc import AsyncIterator

from jat_api.models.contracts import GenerationRequest, GenerationResult, TokenEvent


class SlowTestProvider:
    name = "slow-test"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        text = "JaT slow test provider response."
        return GenerationResult(
            text=text, model=request.model, input_tokens=0, output_tokens=5, finish_reason="stop"
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[TokenEvent]:
        for index, token in enumerate(["JaT ", "slow ", "test ", "provider ", "response."]):
            await asyncio.sleep(0.05)
            yield TokenEvent(text=token, index=index)
