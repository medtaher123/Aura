from typing import Any, Callable

from .event_emitter import EventEmitter, event_emitter


def on_event(event_type: type):
    def decorator(func: Callable):
        if not hasattr(func, "_subscribe_to"):
            func._subscribe_to = []
        func._subscribe_to.append(event_type)
        return func

    return decorator


class EventSubscriberMeta(type):
    def __call__(cls, *args: Any, **kwargs: Any):
        instance = super().__call__(*args, **kwargs)
        emitter: EventEmitter = getattr(instance, "emitter", None) or event_emitter

        for attr_name in dir(instance):
            try:
                attr = getattr(instance, attr_name)
            except AttributeError:
                continue

            if callable(attr) and hasattr(attr, "_subscribe_to"):
                for event_type in getattr(attr, "_subscribe_to", []):
                    emitter.add_listener(event_type, attr)

        return instance


class EventSubscriber(metaclass=EventSubscriberMeta):
    """Base class that auto-registers ``@on_event`` methods on construction.

    Set ``self.emitter`` in ``__init__`` (before returning) to subscribe on a
    non-global bus; otherwise the module-level ``event_emitter`` is used.
    """

    pass
