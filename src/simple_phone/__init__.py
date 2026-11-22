"""SIP test phone built on PJSUA2.

Layers, each built only on the ones before it:

    simple_phone.core        PJSUA2 endpoint, calls, AMD (threads, sync)
    simple_phone             AsyncPhone / Phone, Call, typed events
    simple_phone.cli         the simple-phone command

    from simple_phone import AsyncPhone, Call, Settings
    from simple_phone import pjsua2 as pj   # the bundled bindings
"""

from ._native import pjsua2
from .call import Call
from .events import Event
from .models import (
    Amd,
    CallFailed,
    DigestAuth,
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
    "CallFailed",
    "DigestAuth",
    "Event",
    "Limits",
    "Phone",
    "PhoneError",
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
