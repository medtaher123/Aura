"""Manual demo of weakref cleanup on EventSubscriber (not a pytest module)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from event_subscriber import EventSubscriber, on_event
from event_emitter import event_emitter


@dataclass
class PingEvent:
    pass


class PingResponder(EventSubscriber):
    def __init__(self, name: str):
        self.name = name

    @on_event(PingEvent)
    def on_ping(self, event: PingEvent):
        print(f"{self.name} received Ping!")


async def main():
    print("1. Creating object...")
    responder = PingResponder("Bot-A")
    await event_emitter.emit(PingEvent())

    print("\n2. Deleting object...")
    del responder

    print("3. Emitting event again...")
    await event_emitter.emit(PingEvent())


if __name__ == "__main__":
    asyncio.run(main())
