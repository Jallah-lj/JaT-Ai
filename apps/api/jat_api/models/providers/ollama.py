"""Ollama adapter; isolated behind the JaT provider contract."""

from collections.abc import AsyncIterator

import httpx

from jat_api.models.contracts import GenerationRequest, GenerationResult, TokenEvent


class OllamaProvider:
    name = "ollama"

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint.rstrip("/")

    def _payload(self, request: GenerationRequest, stream: bool) -> dict[str, object]:
        return {
            "model": request.model,
            "messages": [message.__dict__ for message in request.messages],
            "stream": stream,
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.endpoint}/api/chat", json=self._payload(request, False)
            )
            response.raise_for_status()
            data = response.json()
        text = str(data["message"]["content"])
        return GenerationResult(
            text=text,
            model=request.model,
            input_tokens=int(data.get("prompt_eval_count", 0)),
            output_tokens=int(data.get("eval_count", 0)),
            finish_reason="stop",
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[TokenEvent]:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", f"{self.endpoint}/api/chat", json=self._payload(request, True)
            ) as response:
                response.raise_for_status()
                index = 0
                async for data in response.aiter_lines():
                    if not data:
                        continue
                    payload = __import__("json").loads(data)
                    text = str(payload.get("message", {}).get("content", ""))
                    if text:
                        yield TokenEvent(text=text, index=index)
                        index += 1
