"""AsyncPhone (the implementation) and Phone (the same API, synchronous).

    async with AsyncPhone(server="pbx", user="1001", password="...") as phone:
        async with phone.call("1002") as call:          # answered, or CallFailed
            await call.dtmf("1234#")

    with Phone(server="pbx", user="1001", password="...") as phone:   # no await
        with phone.call("1002") as call:
            call.dtmf("1234#")

PJSIP keeps running on the Engine's thread; this module routes its events
to the Call they belong to and turns its commands into awaitables.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
from collections import defaultdict, deque
from dataclasses import replace
from uuid import uuid4

from .call import Call
from .core.engine import Engine
from .core.profiles import derive_account, load_account, load_profile
from .events import CallEvents, PhoneEvents
from .models import (
    Limits,
    PhoneError,
    PoolTimeout,
    RegistrationFailed,
    Settings,
    Timeouts,
    WaitTimeout,
)

log = logging.getLogger(__name__)


class AsyncPhone(PhoneEvents):
    """One SIP account. The first one opened owns the PJSIP endpoint; more
    accounts on the same endpoint come from phone.account().

    Handlers: `@phone.on(Call.Dtmf, digit="#")`. Streams: `phone.events()`.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        password: str | None = None,
        limits: Limits | None = None,
        timeouts: Timeouts | None = None,
        stt=None,
        tts=None,
        **fields,
    ):
        if settings is None:
            settings = Settings(**fields)
        elif fields:
            settings = replace(settings, **fields)
        self.stt, self.tts = stt, tts  # for call.listen() / call.say()
        self.limits = limits or Limits()
        self.timeouts = timeouts or Timeouts()
        # The endpoint takes up to 64 calls (the compiled limit); Limits only
        # paces the calls this phone dials.
        self.settings = replace(settings, max_calls=64)
        self.password = password  # Digest; the login is Settings.auth_user
        self.registered = False
        self.reg = None  # last REGISTER status, e.g. "200 OK"
        self.errors = []  # exceptions raised by handlers
        self._hub: _Hub | None = None
        self._owner = True
        self._handlers = []  # (event type, filters, function)
        self._incoming = asyncio.Queue()
        self._listeners = []  # (queue, types) of events()
        self._pending = defaultdict(deque)  # method -> futures of request()
        self._tasks = set()
        self._reg_failure = None
        self._reg_changed = asyncio.Event()

    @classmethod
    def from_profile(cls, path, **kwargs):
        """A JSON profile (see examples/accounts). The password comes from the
        variable named by its password_env (default SIP_PASSWORD)."""
        values = load_profile(path)
        variable = values.pop("password_env", "SIP_PASSWORD")
        kwargs.setdefault("password", os.environ.get(variable))
        return cls(Settings(**values), **kwargs)

    @property
    def account_id(self):
        return self.settings.account_id

    @property
    def uri(self):
        """Where to dial this account (with the port when not registered)."""
        s = self.settings
        port = f":{s.local_port}" if not s.register and s.local_port else ""
        return f"sip:{s.user}@{s.domain}{port}"

    # -- lifecycle --

    async def __aenter__(self):
        if self._hub is not None:
            raise PhoneError("Phone is already open")
        engine = Engine(self.settings, self.password)
        self._hub = _Hub(engine, asyncio.get_running_loop(), self.limits)
        self._hub.phones[self.account_id] = self
        try:
            await asyncio.to_thread(engine.start)
            await self._ready()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def close(self):
        """Hang up, unregister and stop PJSIP (owner only)."""
        hub, self._hub = self._hub, None
        if hub is None or not self._owner:
            return
        await asyncio.to_thread(hub.engine.stop)
        await asyncio.sleep(0)  # deliver the last events
        hub.unsubscribe()

    async def _ready(self):
        if self.settings.register and self.settings.auto_register:
            await self.wait_registered()

    async def account(self, settings=None, *, password=None, **fields) -> AsyncPhone:
        """Another identity on this endpoint. Shares the SIP port; gets its
        own RTP range and calls.

            await phone.account(user="1002")  # this phone's settings, another user
            await phone.account("1002.json")  # a JSON profile
            await phone.account(Settings(...))
        """
        hub = self._require()
        if isinstance(settings, Settings):
            settings = replace(settings, **fields)
        elif settings is not None:  # a profile path
            settings, variable = load_account(settings, self.settings, len(hub.phones))
            password = password or os.environ.get(variable)
        elif "user" not in fields:
            raise ValueError("account() needs user=... (or Settings, or a profile)")
        else:
            values = {"account_id": fields["user"], **fields}
            settings = derive_account(self.settings, values, len(hub.phones))
        other = AsyncPhone(
            settings,
            password=password,
            limits=self.limits,
            timeouts=self.timeouts,
            stt=self.stt,
            tts=self.tts,
        )
        if other.account_id in hub.phones:
            raise PhoneError(f"Duplicate account_id: {other.account_id}")
        other._hub, other._owner = hub, False
        hub.phones[other.account_id] = other
        await other._run(
            hub.engine.endpoint.open_account, other.password, other.settings
        )
        await other._ready()
        return other

    def _require(self):
        if self._hub is None:
            raise PhoneError("Phone is not open: use 'async with AsyncPhone(...)'")
        return self._hub

    @property
    def _endpoint(self):
        """The core Endpoint: its methods only run through _run()."""
        endpoint = self._require().engine.endpoint
        if endpoint is None:
            raise PhoneError("The PJSUA2 engine has stopped")
        return endpoint

    async def _run(self, function, *args):
        """function(*args) on the engine thread."""
        future = self._require().engine.submit(function, *args)
        try:
            return await asyncio.wrap_future(future)
        except RuntimeError as exc:
            raise PhoneError(str(exc)) from exc

    # -- registration --

    async def wait_registered(self, timeout=None):
        timeout = timeout or self.timeouts.register

        async def until():
            while not self.registered:
                if self._reg_failure:
                    raise RegistrationFailed(*self._reg_failure)
                self._reg_changed.clear()
                await self._reg_changed.wait()

        try:
            await asyncio.wait_for(until(), timeout)
        except TimeoutError:
            raise WaitTimeout("REGISTER", timeout, self.reg) from None

    async def register(self, timeout=None):
        self._reg_failure = None
        await self._run(self._endpoint.set_registration, True, self.account_id)
        await self.wait_registered(timeout)

    async def unregister(self, timeout=None):
        await self._run(self._endpoint.set_registration, False, self.account_id)

        async def until():
            while self.registered:
                self._reg_changed.clear()
                await self._reg_changed.wait()

        await asyncio.wait_for(until(), timeout or self.timeouts.register)

    # -- calls --

    async def dial(self, target, *, headers=None) -> Call:
        """Call a number (sip:number@domain) or a sip: URI. Waits for a free
        slot (Limits), then returns at once; await call.answered() for the
        answer, or use `async with phone.call(...)`."""
        hub = self._require()
        # The Call exists before the core dials, so its first events find it.
        call = Call(self, uuid4().hex[:12])
        await hub.acquire(call, self.timeouts.pool)
        lines = tuple(f"{k}: {v}" for k, v in (headers or {}).items())
        try:
            call.destination = await self._run(
                self._endpoint.start_call, target, lines, self.account_id, call.ref
            )
        except BaseException:
            hub.forget(call)
            raise
        return call

    @contextlib.asynccontextmanager
    async def call(self, target, *, headers=None, timeout=None):
        """An answered call for the `async with` block, hung up after it.
        Raises CallFailed (486, 404...) if it is not answered."""
        call = await self.dial(target, headers=headers)
        try:
            await call.answered(timeout)
            yield call
        finally:
            if call.report is None:
                with contextlib.suppress(PhoneError):
                    await call.hangup()

    async def dial_all(self, targets, handle, *, headers=None):
        """Dial every target within the Limits, run `await handle(call)` on
        each and hang up after. Returns [(target, result)] in the order given;
        a failure (CallFailed, WaitTimeout...) is that target's result."""

        async def one(target):
            try:
                call = await self.dial(target, headers=headers)
            except PhoneError as error:
                return target, error
            try:
                return target, await handle(call)
            except Exception as error:  # noqa: BLE001 - reported per target
                return target, error
            finally:
                with contextlib.suppress(PhoneError):
                    await call.hangup()

        return await asyncio.gather(*(one(target) for target in targets))

    async def incoming(self, timeout=None) -> Call:
        """The next ringing call, when no handler takes Phone.Incoming."""
        try:
            return await asyncio.wait_for(self._incoming.get(), timeout)
        except TimeoutError:
            raise WaitTimeout("an incoming call", timeout) from None

    # -- requests outside a call --

    async def request(
        self, method, target, body="", *, headers=None, content_type="", timeout=None
    ):
        """Any request outside a dialog (OPTIONS, MESSAGE, NOTIFY...).
        Returns the final Phone.Response (method, code, reason). PJSUA sends
        these without credentials: a PBX that challenges them answers 401."""
        method = method.upper()
        future = asyncio.get_running_loop().create_future()
        # shortcut: responses pair with requests by method, in order; two
        # requests of the same method in flight to different targets could swap.
        self._pending[method].append(future)
        lines = tuple(f"{k}: {v}" for k, v in (headers or {}).items())
        try:
            await self._run(
                self._endpoint.send_request,
                method,
                target,
                lines,
                body,
                content_type,
                self.account_id,
            )
            timeout = timeout or self.timeouts.request
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            raise WaitTimeout(f"response to {method}", timeout) from None
        finally:
            with contextlib.suppress(ValueError):
                self._pending[method].remove(future)

    async def options(self, target, **kwargs):
        return await self.request("OPTIONS", target, **kwargs)

    async def message(self, target, text, content_type="text/plain", **kwargs):
        return await self.request(
            "MESSAGE", target, text, content_type=content_type, **kwargs
        )

    # -- presence --

    async def subscribe(self, target, *, dialog=False):
        """Watch `target`: Phone.Presence on each status change, or with
        dialog=True Phone.DialogState instead (BLF: idle, ringing, in a
        call). PJSUA keeps one of the two per target."""
        return await self._run(
            self._endpoint.subscribe, target, dialog, self.account_id
        )

    async def unsubscribe(self, target):
        await self._run(self._endpoint.unsubscribe, target, self.account_id)

    async def set_presence(self, online=True, note=""):
        """What subscribers of this account see (Phone.Presence)."""
        await self._run(self._endpoint.set_presence, online, note, self.account_id)

    async def typing(self, target, typing=True):
        """Tell `target` we are (not) typing a MESSAGE: Phone.Typing there."""
        await self._run(self._endpoint.send_typing, target, typing, self.account_id)

    # -- endpoint --

    async def nat_type(self, timeout=None):
        """The NAT in front of this endpoint, by STUN (Settings.stun_servers):
        a Phone.Nat event, e.g. type "Symmetric" or "Full Cone"."""
        queue = asyncio.Queue()
        entry = (queue, (self.Nat,))
        self._listeners.append(entry)  # before detecting: no result missed
        try:
            await self._run(self._endpoint.detect_nat)
            timeout = timeout or self.timeouts.request
            return await asyncio.wait_for(queue.get(), timeout)
        except TimeoutError:
            raise WaitTimeout("NAT detection", timeout) from None
        finally:
            self._listeners.remove(entry)

    async def configure(self, **changes):
        """media, wav, speaker, record, amd, devices: from the next call on."""
        await self._run(self._endpoint.configure, changes, self.account_id)

    async def devices(self):
        return await self._run(self._endpoint.devices)

    async def codecs(self):
        return await self._run(self._endpoint.codecs)

    async def ip_changed(self):
        """Tell PJSUA the network changed (Wi-Fi/VPN): it re-registers and
        updates live calls."""
        await self._run(self._endpoint.handle_ip_change)

    # -- events and handlers --

    def on(self, event_type, **filters):
        """Decorator: `handler(event)` for each `event_type` whose attributes
        match `filters`, e.g. @phone.on(Call.Dtmf, digit="#"). Sync or async."""

        def register(handler):
            self._handlers.append((event_type, filters, handler))
            return handler

        return register

    async def events(self, *types):
        """Every event of this account (or of `types`), as it happens."""
        queue = asyncio.Queue()
        entry = (queue, types)
        self._listeners.append(entry)
        try:
            while True:
                yield await queue.get()
        finally:
            self._listeners.remove(entry)

    async def serve(self):
        """Keep running the handlers until cancelled (Ctrl+C)."""
        self._require()
        await asyncio.Event().wait()

    def _push(self, event):
        if isinstance(event, self.Registration):
            self._registration(event)
        elif isinstance(event, self.Response):
            self._resolve(event)
        for queue, types in self._listeners:
            if not types or isinstance(event, types):
                queue.put_nowait(event)
        handlers = [
            handler
            for event_type, filters, handler in self._handlers
            if isinstance(event, event_type)
            and all(
                getattr(event, key, None) == value for key, value in filters.items()
            )
        ]
        for handler in handlers:
            self._start(handler, event)
        if isinstance(event, self.Incoming) and not handlers and event.call is not None:
            self._incoming.put_nowait(event.call)

    def _registration(self, event):
        self.registered = event.active
        self.reg = f"{event.code} {event.reason}"
        # PJSUA answers the Digest challenge itself: a 401/407 here is
        # final (wrong password, or none).
        if event.code >= 300:
            self._reg_failure = (event.code, event.reason)
        self._reg_changed.set()

    def _resolve(self, response):
        """Hand a Response to the oldest request() still waiting for it."""
        waiting = self._pending[response.method]
        while waiting:
            future = waiting.popleft()
            if not future.done():
                future.set_result(response)
                return

    def _start(self, handler, event):
        try:
            result = handler(event)
        except Exception as exc:  # noqa: BLE001 - a handler must not stop dispatch
            self._handler_failed(handler, exc)
            return
        if inspect.isawaitable(result):
            task = asyncio.ensure_future(result)
            self._tasks.add(task)
            task.add_done_callback(lambda t: self._task_done(handler, t))

    def _task_done(self, handler, task):
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            self._handler_failed(handler, task.exception())

    def _handler_failed(self, handler, exc):
        self.errors.append(exc)
        log.error(
            "handler %s failed", getattr(handler, "__name__", handler), exc_info=exc
        )


def for_call(event, phone, call):
    """The event as seen by `call` (plus Answered on the first CONFIRMED)."""
    if isinstance(event, PhoneEvents.Sip):  # matched to the call by Call-ID
        event = CallEvents.Sip(
            message=event.message, at=event.at, account_id=event.account_id
        )
    event = replace(event, phone=phone, call=call, ref=call.ref)
    if (
        isinstance(event, CallEvents.StateChanged)
        and event.state == "CONFIRMED"
        and call.answered_at is None
    ):
        return [event, CallEvents.Answered(at=event.at, phone=phone, call=call)]
    return [event]


class _Hub:
    """Routes engine events (engine thread) to Phones and Calls (event loop),
    and keeps the endpoint's call slots (Limits)."""

    def __init__(self, engine, loop, limits):
        self.engine = engine
        self.loop = loop
        self.limits = limits
        self.phones: dict[str, AsyncPhone] = {}
        self.calls: dict[str, Call] = {}  # live calls by ref
        # Calls that just ended: the BYE and its 200 are logged after the
        # call is over, and still belong to it.
        self.ended: dict[str, Call] = {}
        # An incoming INVITE is logged before PJSIP creates its call:
        # (account_id, Call-ID) -> those events, until Phone.Incoming.
        self.early: dict = {}
        self.next_dial = 0.0  # calls_per_second pacing
        self.slots_changed = asyncio.Event()
        self.unsubscribe = engine.subscribe(self._from_engine)

    # -- limits --

    async def acquire(self, call, timeout):
        """A slot for `call` (Limits.max_calls), then the pacing of
        calls_per_second. The call holds the slot from here on."""

        async def free():
            while self.outgoing() >= self.limits.max_calls:
                self.slots_changed.clear()
                await self.slots_changed.wait()

        try:
            await asyncio.wait_for(free(), timeout)
        except TimeoutError:
            raise PoolTimeout("a free call slot", timeout) from None
        self.calls[call.ref] = call
        if self.limits.calls_per_second:
            now = self.loop.time()
            start = max(now, self.next_dial)
            self.next_dial = start + 1 / self.limits.calls_per_second
            await asyncio.sleep(start - now)

    def outgoing(self):
        return sum(1 for call in self.calls.values() if not call.incoming)

    def forget(self, call):
        """A dial that failed before the core took the call."""
        self.calls.pop(call.ref, None)
        self.slots_changed.set()

    # -- routing --

    def _from_engine(self, event):
        try:
            self.loop.call_soon_threadsafe(self.dispatch, event)
        except RuntimeError:
            pass  # the loop is closed: nobody is listening any more

    def _hold(self, key, event):
        self.early.setdefault(key, []).append(event)
        while len(self.early) > 100:
            self.early.pop(next(iter(self.early)))

    def adopt(self, phone, ref, call_id):
        """The Call of a new incoming call, with the SIP logged before it."""
        call = self.calls[ref] = Call(phone, ref, incoming=True)
        self.slots_changed.set()
        for event in self.early.pop((phone.account_id, call_id), []):
            self._deliver(call, for_call(event, phone, call))
        return call

    def dispatch(self, event):
        """A typed event from the core: give it its phone and call."""
        phone = self.phones.get(event.account_id or "")
        call = self._call_for(event, phone)
        if call is None:
            if not event.ref and isinstance(event, (CallEvents.Sip, PhoneEvents.Sip)):
                self._hold((event.account_id, event.message.call_id), event)
            if phone is not None:
                phone._push(replace(event, phone=phone))
            return
        phone = phone or call.phone
        events = for_call(event, phone, call)
        self._deliver(call, events)
        for typed in events:
            phone._push(typed)

    def _call_for(self, event, phone):
        """The Call an event belongs to; a new one for an incoming call."""
        if not event.ref:
            return None
        call = self.calls.get(event.ref) or self.ended.get(event.ref)
        if call is None and isinstance(event, PhoneEvents.Incoming) and phone:
            call = self.adopt(phone, event.ref, event.call_id)
        return call

    def _deliver(self, call, events):
        for event in events:
            call._push(event)
        if call.report is not None and call.ref in self.calls:
            self.calls.pop(call.ref, None)
            self.ended[call.ref] = call
            while len(self.ended) > 100:
                self.ended.pop(next(iter(self.ended)))
            self.slots_changed.set()
