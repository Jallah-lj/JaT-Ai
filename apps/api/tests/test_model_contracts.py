import pytest

from jat_api.models import ChatMessage, GenerationRequest, create_provider


@pytest.mark.asyncio
async def test_deterministic_provider_supports_non_streaming_and_streaming_contracts() -> None:
    provider = create_provider("deterministic")
    request = GenerationRequest(
        messages=[ChatMessage(role="user", content="hello JaT")],
        model="jat-development",
        max_tokens=128,
        temperature=0.2,
        context_length=8192,
    )
    result = await provider.generate(request)
    streamed = "".join([event.text async for event in provider.stream(request)])
    assert result.text == "JaT development provider received: hello JaT"
    assert streamed == result.text


def test_unknown_provider_fails_safely() -> None:
    with pytest.raises(ValueError, match="Unsupported MODEL_PROVIDER"):
        create_provider("untrusted-provider")


@pytest.mark.asyncio
async def test_slow_provider_stream_can_be_cancelled() -> None:
    import asyncio

    provider = create_provider("slow-test")
    request = GenerationRequest(
        messages=[], model="test", max_tokens=8, temperature=0.0, context_length=256
    )
    stream = provider.stream(request)
    assert (await anext(stream)).text == "JaT "
    task = asyncio.create_task(anext(stream))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_ollama_payload_forwards_context_window_system_message_and_options() -> None:
    from jat_api.models.providers.ollama import OllamaProvider

    provider = OllamaProvider("http://localhost:11434/")
    request = GenerationRequest(
        messages=[
            ChatMessage(role="system", content="Be concise."),
            ChatMessage(role="user", content="hello"),
        ],
        model="llama3.1",
        max_tokens=256,
        temperature=0.3,
        context_length=4096,
    )

    payload = provider._payload(request, stream=False)

    assert provider.endpoint == "http://localhost:11434"  # trailing slash stripped
    assert payload["model"] == "llama3.1"
    assert payload["stream"] is False
    # System instructions lead the message list sent to the model.
    assert payload["messages"][0] == {"role": "system", "content": "Be concise."}
    assert payload["messages"][1] == {"role": "user", "content": "hello"}
    options = payload["options"]
    assert options["temperature"] == 0.3
    assert options["num_predict"] == 256
    assert options["num_ctx"] == 4096  # context window forwarded, not silently dropped
