"""Phone: AsyncPhone without await, run on its own event loop thread."""

import asyncio
import inspect
import threading

from .call import Call
from .events import PhoneEvents
from .phone import AsyncPhone


class Phone(PhoneEvents):
    """AsyncPhone without await: the same API, run on its own event loop
    thread (like httpx.Client next to httpx.AsyncClient).

    Handlers registered here run on that loop: write them as `async def`.
    """

    def __init__(self, *args, **kwargs):
        self._start(AsyncPhone, *args, **kwargs)

    @classmethod
    def from_profile(cls, path, **kwargs):
        phone = cls.__new__(cls)
        phone._start(AsyncPhone.from_profile, path, **kwargs)
        return phone

    def _start(self, factory, *args, **kwargs):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="simple-phone", daemon=True
        )
        self._thread.start()

        async def create():  # built on the loop it will run on
            return factory(*args, **kwargs)

        self._async = self._portal(create())

    def _portal(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result()

    def __enter__(self):
        self._portal(self._async.__aenter__())
        return self

    def __exit__(self, *exc):
        try:
            self._portal(self._async.__aexit__(*exc))
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(5)

    def __getattr__(self, name):
        return _sync(getattr(self._async, name), self._portal)

    def __repr__(self):
        return f"<Phone {self._async.uri}>"


class _SyncProxy:
    """A Call (or AsyncPhone) seen through the sync portal."""

    def __init__(self, target, portal):
        self._target, self._portal = target, portal

    def __getattr__(self, name):
        return _sync(getattr(self._target, name), self._portal)

    def __repr__(self):
        return repr(self._target)


class _SyncContext:
    def __init__(self, manager, portal):
        self._manager, self._portal = manager, portal

    def __enter__(self):
        return _sync_value(self._portal(self._manager.__aenter__()), self._portal)

    def __exit__(self, *exc):
        return self._portal(self._manager.__aexit__(*exc))


def _sync(value, portal):
    if isinstance(value, type) or not callable(value):
        return _sync_value(value, portal)

    def blocking(*args, **kwargs):
        return _sync_value(value(*args, **kwargs), portal)

    return blocking


def _sync_value(value, portal):
    if inspect.iscoroutine(value):
        return _sync_value(portal(value), portal)
    if inspect.isasyncgen(value):
        return _sync_iter(value, portal)
    if isinstance(value, (Call, AsyncPhone)):
        return _SyncProxy(value, portal)
    if hasattr(value, "__aenter__"):
        return _SyncContext(value, portal)
    return value


def _sync_iter(agen, portal):
    while True:
        try:
            item = portal(agen.__anext__())
        except StopAsyncIteration:
            return
        yield _sync_value(item, portal)
