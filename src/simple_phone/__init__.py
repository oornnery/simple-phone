"""SIP test phone built on PJSUA2.

Layers, each built only on the ones before it:

    simple_phone.core        PJSUA2 endpoint, calls, AMD (threads, sync)
    simple_phone             AsyncPhone / Phone, Call, typed events
    simple_phone.cli         the simple-phone command

    from simple_phone import AsyncPhone, Call, Settings
    from simple_phone import pjsua2 as pj   # the bundled bindings
"""

# Python 3.15+ (PEP 810) loads these on first use, so `import simple_phone`
# and `simple-phone --help` skip PJSIP and asyncio. Older Pythons ignore it.
__lazy_modules__ = [
    "simple_phone._native",
    "simple_phone.call",
    "simple_phone.events",
    "simple_phone.models",
    "simple_phone.phone",
    "simple_phone.sync",
]

from ._native import pjsua2
from .call import Call
from .events import CallEvent, Event, PhoneEvent
from .models import (
    Amd,
    CallFailed,
    Limits,
    PhoneError,
    PoolTimeout,
    RegistrationFailed,
    Report,
    Settings,
    Stats,
    Timeouts,
    WaitTimeout,
)
from .phone import AsyncPhone
from .sync import Phone
from .version import __version__

__all__ = [
    "Amd",
    "AsyncPhone",
    "Call",
    "CallEvent",
    "CallFailed",
    "Event",
    "Limits",
    "Phone",
    "PhoneError",
    "PhoneEvent",
    "PoolTimeout",
    "RegistrationFailed",
    "Report",
    "Settings",
    "Stats",
    "Timeouts",
    "WaitTimeout",
    "__version__",
    "pjsua2",
]
