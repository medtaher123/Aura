import threading
from typing import Any

class SingletonMeta(type):
    """
    A thread-safe implementation of Singleton using a metaclass.
    """
    _instances: dict[type, Any] = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs) -> Any:
        # Fast path: check if the instance exists without acquiring the lock
        if cls not in cls._instances:
            # Slow path: acquire the lock and double-check
            with cls._lock:
                if cls not in cls._instances:
                    # super().__call__ triggers the class's __new__ and __init__
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        
        return cls._instances[cls]