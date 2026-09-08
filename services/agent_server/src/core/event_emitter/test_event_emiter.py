"""Manual demo of EventEmitter stream handlers (not a pytest module)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from event_emitter import event_emitter


@dataclass
class TokenStreamEvent:
    chunk: str


@dataclass
class StreamCompleteEvent:
    total_tokens: int


@event_emitter.on(TokenStreamEvent)
async def async_logger(event: TokenStreamEvent):
    await asyncio.sleep(0.01)
    print(f"[Async DB Writer] Saved chunk: '{event.chunk}'")


@event_emitter.on(TokenStreamEvent)
def sync_logger(event: TokenStreamEvent):
    print(f"[Sync Console] Rendered: '{event.chunk}'")


@event_emitter.on(StreamCompleteEvent)
async def handle_completion(event: StreamCompleteEvent):
    print(f"\nStream finished! Total tokens processed: {event.total_tokens}")


class MockLLMRouter:
    async def call_stream(self, system_prompt: str, user_prompt: str, max_tokens: int):
        simulated_response = ["Hello", ", ", "this ", "is ", "a ", "test ", "stream."]
        for word in simulated_response:
            await asyncio.sleep(0.1)
            yield word


async def main():
    print("Starting LLM Stream...\n" + "-" * 30)

    router = MockLLMRouter()
    token_count = 0

    async for chunk in router.call_stream(
        system_prompt="You are a helpful AI.",
        user_prompt="Say hi!",
        max_tokens=900,
    ):
        if not chunk:
            continue

        token_count += 1
        await event_emitter.emit(TokenStreamEvent(chunk=chunk))

    await event_emitter.emit(StreamCompleteEvent(total_tokens=token_count))


if __name__ == "__main__":
    asyncio.run(main())
