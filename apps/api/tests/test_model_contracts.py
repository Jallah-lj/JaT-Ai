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
