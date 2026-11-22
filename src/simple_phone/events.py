"""Typed events, grouped like Textual messages: Call.Dtmf, Phone.Incoming...

Every event has `at` (epoch seconds), `phone` and `call` (None for account
events). The core creates them; the API fills in `phone` and `call`. Handlers are found by type
(`@phone.on(Call.Dtmf)`) or by name in a subclass (`on_call_dtmf`), like
Textual's `on_button_pressed`.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .core.sip import SipMessage
from .models import Amd, Report, Stats


@dataclass(kw_only=True)
class Event:
    at: float = field(default_factory=time.time)
    phone: Any = field(default=None, repr=False)
    call: Any = field(default=None, repr=False)
    # Routing, set by the core: account, call reference, SIP Call-ID.
    account_id: str | None = field(default=None, repr=False)
    ref: str | None = field(default=None, repr=False)
    call_id: str | None = field(default=None, repr=False)

    namespace: ClassVar[str] = ""
    handler_name: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
        cls.handler_name = f"on_{cls.namespace}_{snake}"


class CallEvent(Event):
    namespace = "call"


class PhoneEvent(Event):
    namespace = "phone"


class CallEvents:
    """Events of one call. Reached as Call.<Name>."""

    @dataclass(kw_only=True)
    class StateChanged(CallEvent):
        state: str  # CALLING EARLY CONNECTING CONFIRMED DISCONNECTED INCOMING
        code: int
        reason: str
        remote_uri: str = ""

    @dataclass(kw_only=True)
    class Answered(CallEvent):
        pass

    @dataclass(kw_only=True)
    class Ended(CallEvent):
        report: Report

    @dataclass(kw_only=True)
    class Sip(CallEvent):
        message: SipMessage

    @dataclass(kw_only=True)
    class Dtmf(CallEvent):  # received
        digit: str
        method: str = "rfc4733"

    @dataclass(kw_only=True)
    class DtmfSent(CallEvent):
        digits: str
        method: str

    @dataclass(kw_only=True)
    class MediaChanged(CallEvent):
        status: str = ""  # ACTIVE LOCAL_HOLD REMOTE_HOLD ...
        held: bool = False

    @dataclass(kw_only=True)
    class Stats(CallEvent):
        stats: Stats

    @dataclass(kw_only=True)
    class Amd(CallEvent):
        amd: Amd

        @property
        def result(self):
            return self.amd.result

    @dataclass(kw_only=True)
    class Transaction(CallEvent):  # in-dialog request/response (INFO, UPDATE...)
        method: str
        code: int
        reason: str

    @dataclass(kw_only=True)
    class TransferStatus(CallEvent):  # progress of a transfer we sent
        code: int
        reason: str
        final: bool
        success: bool

    @dataclass(kw_only=True)
    class TransferRequest(CallEvent):  # REFER received
        target: str
        accepted: bool

    @dataclass(kw_only=True)
    class Redirected(CallEvent):  # 3xx
        target: str
        followed: bool

    @dataclass(kw_only=True)
    class Reinvite(CallEvent):
        has_offer: bool

    @dataclass(kw_only=True)
    class Text(CallEvent):  # RTT received: characters as typed (\b erases)
        text: str

    @dataclass(kw_only=True)
    class Message(CallEvent):  # in-dialog MESSAGE
        from_uri: str
        content_type: str
        body: str

    @dataclass(kw_only=True)
    class AudioChanged(CallEvent):
        muted: bool
        microphone: float
        speaker: float

    @dataclass(kw_only=True)
    class Recording(CallEvent):
        path: str | None

    @dataclass(kw_only=True)
    class Insight(CallEvent):  # what an observing agent concluded from `text`
        text: str
        output: Any


class PhoneEvents:
    """Events of a phone (an account). Reached as Phone.<Name> or
    AsyncPhone.<Name>: the same types."""

    @dataclass(kw_only=True)
    class Incoming(PhoneEvent):  # `call` is the ringing call
        remote_uri: str

    @dataclass(kw_only=True)
    class Registration(PhoneEvent):  # every REGISTER result
        code: int
        reason: str
        active: bool

    @dataclass(kw_only=True)
    class Registered(PhoneEvent):
        code: int
        reason: str

    @dataclass(kw_only=True)
    class RegistrationFailed(PhoneEvent):
        code: int
        reason: str

    @dataclass(kw_only=True)
    class Sip(PhoneEvent):  # outside a call: REGISTER, OPTIONS, MESSAGE...
        message: SipMessage

    @dataclass(kw_only=True)
    class Response(PhoneEvent):  # final answer to phone.request()
        method: str
        code: int
        reason: str

    @dataclass(kw_only=True)
    class Message(PhoneEvent):  # MESSAGE received outside a call
        from_uri: str
        content_type: str
        body: str

    @dataclass(kw_only=True)
    class Mwi(PhoneEvent):  # voicemail status (Settings.mwi)
        waiting: bool  # Messages-Waiting: yes
        body: str  # the message-summary, e.g. "Voice-Message: 2/8 (0/0)"

    @dataclass(kw_only=True)
    class Presence(PhoneEvent):  # NOTIFY for phone.subscribe(uri)
        uri: str
        online: bool | None  # None: unknown
        status: str  # "Online", "Busy"...
        note: str

    @dataclass(kw_only=True)
    class DialogState(PhoneEvent):  # BLF: phone.subscribe(uri, dialog=True)
        uri: str  # the monitored entity
        state: str  # terminated (idle), trying, proceeding, early, confirmed
        body: str  # the dialog-info XML

    @dataclass(kw_only=True)
    class Typing(PhoneEvent):  # RFC 3994 is-composing
        from_uri: str
        typing: bool

    @dataclass(kw_only=True)
    class Rejected(PhoneEvent):  # INVITE refused by PJSUA before any Call
        code: int
        reason: str
        remote_uri: str

    @dataclass(kw_only=True)
    class Nat(PhoneEvent):  # phone.nat_type()
        type: str  # "Symmetric", "Full cone"...
        ok: bool
        reason: str

    @dataclass(kw_only=True)
    class AccountChanged(PhoneEvent):
        action: str  # added, updated, removed

    @dataclass(kw_only=True)
    class Log(PhoneEvent):
        level: int
        text: str

    @dataclass(kw_only=True)
    class Warning(PhoneEvent):
        text: str

    @dataclass(kw_only=True)
    class Info(PhoneEvent):
        text: str
