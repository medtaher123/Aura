import asyncio
import inspect
import weakref
from collections import defaultdict
from typing import Any, Callable


class _StrongRef:
    """Fallback when a callable cannot be weakly referenced (e.g. list.append)."""

    __slots__ = ("_obj",)

    def __init__(self, obj: Callable) -> None:
        self._obj = obj

    def __call__(self) -> Callable:
        return self._obj

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _StrongRef) and self._obj is other._obj

    def __hash__(self) -> int:
        return hash(id(self._obj))


def _make_handler_ref(handler: Callable) -> Any:
    if inspect.ismethod(handler):
        try:
            return weakref.WeakMethod(handler)
        except TypeError:
            pass
    # Builtin bound methods (e.g. list.append) may accept weakref.ref in 3.13+,
    # but the temporary method object is GC'd right after the call site — keep
    # a strong ref instead.
    if hasattr(handler, "__self__"):
        return _StrongRef(handler)
    try:
        return weakref.ref(handler)
    except TypeError:
        return _StrongRef(handler)


class EventEmitter:
    def __init__(self) -> None:
        self._subscribers: dict[type, list[Any]] = defaultdict(list)

    def on(self, event_type: type):
        def decorator(func: Callable):
            self.add_listener(event_type, func)
            return func

        return decorator

    def add_listener(self, event_type: type, handler: Callable) -> None:
        ref = _make_handler_ref(handler)
        if ref not in self._subscribers[event_type]:
            self._subscribers[event_type].append(ref)

    def off(self, event_type: type, handler: Callable) -> None:
        ref = _make_handler_ref(handler)
        if ref in self._subscribers.get(event_type, []):
            self._subscribers[event_type].remove(ref)

    def _active_handlers(self, event_type: type) -> list[Callable]:
        refs = self._subscribers.get(event_type, [])
        active_refs: list[Any] = []
        handlers: list[Callable] = []

        for ref in refs:
            handler = ref()
            if handler is None:
                continue
            active_refs.append(ref)
            handlers.append(handler)

        self._subscribers[event_type] = active_refs
        return handlers

    async def emit(self, event: Any) -> None:
        event_type = type(event)
        handlers = self._active_handlers(event_type)
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
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result, handler in zip(results, async_handlers):
                if isinstance(result, Exception):
                    print(f"Async handler {handler.__name__} failed: {result}")

    def emit_sync(self, event: Any) -> None:
        """Emit to sync handlers immediately; schedule async handlers if a loop is running."""
        event_type = type(event)
        handlers = self._active_handlers(event_type)
        if not handlers:
            return

        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        for handler in handlers:
            if inspect.iscoroutinefunction(handler):
                if loop is None:
                    print(
                        f"Async handler {handler.__name__} skipped: no running event loop"
                    )
                    continue
                task = loop.create_task(handler(event))

                def _log_failure(
                    done: asyncio.Task, *, name: str = handler.__name__
                ) -> None:
                    try:
                        exc = done.exception()
                    except asyncio.CancelledError:
                        return
                    if exc is not None:
                        print(f"Async handler {name} failed: {exc}")

                task.add_done_callback(_log_failure)
            else:
                try:
                    handler(event)
                except Exception as e:
                    print(f"Sync handler {handler.__name__} failed: {e}")


event_emitter = EventEmitter()
