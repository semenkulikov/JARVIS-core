"""A value created on first use, owned by the composition root instead of a module global."""
from __future__ import annotations

import threading
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class Lazy(Generic[T]):
    def __init__(self, factory: Callable[[], T]) -> None:
        self._factory = factory
        self._value: T | None = None
        self._lock = threading.Lock()

    def get(self) -> T:
        if self._value is None:
            with self._lock:
                if self._value is None: self._value = self._factory()
        return self._value

    def peek(self) -> T | None:
        """The value if it was already created; never creates it."""
        return self._value

    def set(self, value: T) -> None:
        self._value = value
