"""SIP messages recovered from the PJSIP log: the ladder of each call.

PJSIP logs every message it sends or receives at level 4, in one entry:

    TX 1524 bytes Request msg INVITE/cseq=1 (tdta0x...) to UDP 10.0.0.1:5060:
    INVITE sip:1002@pbx SIP/2.0
    ...
    --end msg--

The log line is capped by PJ_LOG_MAX_SIZE (4000 bytes), so a very large
message can arrive cut short. It is kept, marked as truncated.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

_TRACE = re.compile(
    r"(?P<dir>TX|RX) \d+ bytes .*? (?:to|from) (?P<transport>\S+) (?P<peer>\S+):\r?\n"
    r"(?P<raw>.*?)(?P<end>\r?\n--end msg--|\Z)",
    re.DOTALL,
)
_COMPACT = {
    "i": "call-id",
    "f": "from",
    "t": "to",
    "v": "via",
    "m": "contact",
    "c": "content-type",
    "l": "content-length",
    "k": "supported",
}


@dataclass
class SipMessage:
    direction: str  # "TX" sent by us, "RX" received
    transport: str
    peer: str  # host:port of the other side
    raw: str
    truncated: bool = False
    at: float = field(default_factory=time.time)
    first_line: str = ""
    method: str | None = None  # requests
    code: int | None = None  # responses
    reason: str = ""
    # Lower-case header name -> first value.
    headers: dict[str, str] = field(default_factory=dict)
    cseq_method: str | None = None
    cseq_number: int | None = None

    def __post_init__(self) -> None:
        head, _, _ = self.raw.replace("\r\n", "\n").partition("\n\n")
        lines = head.split("\n")
        self.first_line = lines[0].strip()
        for line in lines[1:]:
            name, sep, value = line.partition(":")
            if sep:
                name = name.strip().lower()
                self.headers.setdefault(_COMPACT.get(name, name), value.strip())
        cseq = self.headers.get("cseq", "").split()
        if len(cseq) == 2 and cseq[0].isdigit():
            self.cseq_number, self.cseq_method = int(cseq[0]), cseq[1].upper()
        parts = self.first_line.split(" ", 2)
        if parts[0].startswith("SIP/") and len(parts) > 1 and parts[1].isdigit():
            self.code = int(parts[1])
            self.reason = parts[2] if len(parts) > 2 else ""
        else:
            self.method = parts[0]

    @property
    def is_request(self) -> bool:
        return self.method is not None

    @property
    def call_id(self) -> str:
        return self.headers.get("call-id", "")

    @property
    def has_sdp(self) -> bool:
        return "application/sdp" in self.headers.get("content-type", "")

    @property
    def label(self) -> str:
        """INVITE (SDP) | 180 Ringing · INVITE"""
        if self.method is not None:
            text = self.method
        else:
            text = f"{self.code} {self.reason} · {self.cseq_method}"
        return text + (" (SDP)" if self.has_sdp else "")


# BLF: the busiest dialog wins; a NOTIFY without any means idle.
_DIALOG_STATES = ("confirmed", "early", "proceeding", "trying")


def dialog_state(msg: SipMessage) -> tuple[str, str, str] | None:
    """(entity, state, body) of a received dialog-event NOTIFY, else None."""
    event = msg.headers.get("event", "").lower()
    if (
        msg.direction != "RX"
        or msg.method != "NOTIFY"
        or not event.startswith("dialog")
    ):
        return None
    body = msg.raw.replace("\r\n", "\n").partition("\n\n")[2]
    entity = re.search(r'entity="([^"]+)"', body)
    states = set(re.findall(r"<state[^>]*>\s*(\w+)\s*</state>", body))
    state = next((s for s in _DIALOG_STATES if s in states), "terminated")
    return (entity[1] if entity else msg.headers.get("from", ""), state, body)


def parse_trace(text: str) -> SipMessage | None:
    """The SipMessage in one PJSIP log entry, or None."""
    if "bytes" not in text:
        return None
    match = _TRACE.search(text)
    if not match:
        return None
    return SipMessage(
        direction=match["dir"],
        transport=match["transport"],
        peer=match["peer"],
        raw=match["raw"],
        truncated=not match["end"],
    )
