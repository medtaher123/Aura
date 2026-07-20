import asyncio
import inspect
from dataclasses import dataclass
from collections import defaultdict
from typing import Callable, Any

class EventEmitter:
    def __init__(self):
        # Maps an Event Dataclass to a list of handler functions
        self._subscribers: dict[type, list[Callable]] = defaultdict(list)

    def on(self, event_type: type):
        """Decorator to subscribe a function to an event."""
        def decorator(func: Callable):
            self.add_listener(event_type, func)
            return func
        return decorator

    def add_listener(self, event_type: type, handler: Callable):
        """Dynamically subscribe a handler to an event."""
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)

    def off(self, event_type: type, handler: Callable):
        """Unsubscribe a handler to prevent memory leaks or stop listening."""
        if handler in self._subscribers.get(event_type, []):
            self._subscribers[event_type].remove(handler)

    async def emit(self, event: Any):
        """Emits an event to all subscribers concurrently."""
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])
        
        if not handlers:
            return

        tasks = []
        async_handlers = []
        
        for handler in handlers:
            if inspect.iscoroutinefunction(handler):
                tasks.append(asyncio.create_task(handler(event)))
                async_handlers.append(handler)
            else:
                try:
                    handler(event)
                except Exception as e:
                    print(f"Sync handler {handler.__name__} failed: {e}")

        if tasks:
            # Wait for all async handlers, safely catching exceptions
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result, handler in zip(results, async_handlers):
                if isinstance(result, Exception):
                    print(f"Async handler {handler.__name__} failed: {result}")

event_emitter = EventEmitter()