"""Runs an Endpoint on its own thread, so the async API can drive it.

PJSUA2 is single-threaded here (mainThreadOnly): the engine thread creates
the library, runs libHandleEvents() and executes every command. Other
threads only send commands (Engine.run / Engine.submit) and receive Events
through listeners. Listeners are called on the engine thread and must return
quickly: hand the event to your own loop (a queue,
asyncio call_soon_threadsafe for a web server, ...).
"""

import queue
import threading
import time
from concurrent.futures import Future

from .._native import pjsua2 as pj
from ..events import CallEvents as C
from ..events import PhoneEvents as P
from ..models import Stats
from .endpoint import Endpoint

START_TIMEOUT = 35  # seconds for PJSUA to start (transport, sound device)


class Engine:
    _endpoint_lock = threading.Lock()

    def __init__(self, config, password=None):
        self.config = config
        self.password = password
        self.listeners = []
        self.jobs = queue.Queue()
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.thread = self.endpoint = None
        self.error = None

    # -- events --

    def subscribe(self, listener):
        """Call `listener(event)` for every event. Returns an unsubscribe."""
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def emit(self, event):
        for listener in list(self.listeners):
            try:
                listener(event)
            except Exception:  # noqa: BLE001, S110 - one bad listener must not stop the rest
                pass

    # -- lifecycle --

    def start(self):
        """Start the library and the account (REGISTER runs in background)."""
        if self.thread is not None:
            raise RuntimeError("Engine cannot be started twice")
        self.thread = threading.Thread(target=self._main, name="pjsua", daemon=True)
        self.thread.start()
        if not self.ready.wait(START_TIMEOUT):
            self.stop()
            raise TimeoutError("Endpoint startup timed out")
        if self.error:
            raise RuntimeError(self.error)
        return self

    def stop(self, timeout=15):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(timeout)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def _main(self):
        acquired = self._endpoint_lock.acquire(blocking=False)
        try:
            if not acquired:
                raise RuntimeError(
                    "Only one Engine per process; use accounts/calls or separate processes"
                )
            with Endpoint(self.config, self.emit) as endpoint:
                endpoint.open_account(self.password)
                self.endpoint = endpoint
                self.ready.set()
                self._loop(endpoint)
                self._cancel_jobs()
        except Exception as exc:  # noqa: BLE001 - boundary reports errors without stopping callbacks/workers
            self.error = exc.info() if isinstance(exc, pj.Error) else str(exc)
            self.emit(P.Warning(text=f"Engine stopped: {self.error}"))
        finally:
            self.endpoint = None
            self.ready.set()
            self._cancel_jobs()
            if acquired:
                self._endpoint_lock.release()

    def _loop(self, endpoint):
        next_sample = 0.0
        while not self.stopping.is_set():
            self._run_jobs()
            endpoint.poll(step_ms=20)
            endpoint.reap()
            for call in list(endpoint.calls.values()):
                call.poll_amd()
            call = None
            now = time.monotonic()
            if now >= next_sample:
                next_sample = now + self.config.stats_interval
                self._sample(endpoint)

    def _sample(self, endpoint):
        """Report call errors and emit Call.Stats for every call."""
        for call in list(endpoint.calls.values()):
            if call.error:
                endpoint.warn(call.error, **call.identity())
                call.error = None
            call.sample()
            if stats := Stats.parse(list(call.streams.values())):
                call.emit(C.Stats, stats=stats)

    def _run_jobs(self):
        while True:
            try:
                future, function, args = self.jobs.get_nowait()
            except queue.Empty:
                return
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(function(*args))
            except pj.Error as exc:
                future.set_exception(RuntimeError(exc.reason or exc.info()))
            except Exception as exc:  # noqa: BLE001 - boundary reports errors without stopping callbacks/workers
                future.set_exception(exc)

    def _cancel_jobs(self):
        while True:
            try:
                future, _, _ = self.jobs.get_nowait()
            except queue.Empty:
                return
            if future.set_running_or_notify_cancel():
                future.set_exception(RuntimeError("Engine stopped"))

    # -- commands (any thread) --

    def submit(self, function, *args):
        """Run function(*args) on the engine thread, where every PJSUA2 call
        must happen. Returns a Future."""
        future = Future()
        if self.thread is None or self.stopping.is_set() or self.error:
            future.set_exception(RuntimeError("Engine stopped"))
        else:
            self.jobs.put((future, function, args))
        return future

    def run(self, function, *args, timeout=10):
        """Like submit(), but waits for the result (or raises its error)."""
        return self.submit(function, *args).result(timeout)
