"""Settings, limits, errors and the result types of the public API."""

from __future__ import annotations

from dataclasses import dataclass

from .core.config import Config as Settings

__all__ = [
    "Amd",
    "CallFailed",
    "DigestAuth",
    "Limits",
    "PhoneError",
    "PoolTimeout",
    "RegistrationFailed",
    "Report",
    "Settings",
    "Stats",
    "Timeouts",
    "WaitTimeout",
]


# -- configuration --


@dataclass(frozen=True)
class DigestAuth:
    """SIP Digest credentials. `username` defaults to the account's user."""

    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class Limits:
    """Like httpx.Limits, for the calls a phone dials. `max_calls`: dialed
    calls at once (SIPp -l; the endpoint holds up to 64 calls in total);
    dial() waits for a slot. `calls_per_second`: new calls per second
    (SIPp -r); None = unlimited. Incoming calls beyond 64 get 486."""

    max_calls: int = 4
    calls_per_second: float | None = None

    def __post_init__(self):
        if not 1 <= self.max_calls <= 64:
            raise ValueError("max_calls must be between 1 and 64")
        if self.calls_per_second is not None and self.calls_per_second <= 0:
            raise ValueError("calls_per_second must be positive")


@dataclass(frozen=True)
class Timeouts:
    """Default waits, in seconds. `pool`: for a free call slot (Limits)."""

    register: float = 30
    setup: float = 30  # until answered
    pool: float = 30
    request: float = 10  # out-of-dialog and in-dialog requests


# -- errors --


class PhoneError(Exception):
    pass


class RegistrationFailed(PhoneError):
    def __init__(self, code, reason):
        super().__init__(f"REGISTER rejected: {code} {reason}")
        self.code, self.reason = code, reason


class CallFailed(PhoneError):
    """The call ended before what you were waiting for."""

    def __init__(self, code, reason, waiting_for):
        super().__init__(f"{code} {reason} (waiting for {waiting_for})")
        self.code, self.reason, self.waiting_for = code, reason, waiting_for


class WaitTimeout(PhoneError, TimeoutError):
    def __init__(self, waiting_for, timeout, state=None):
        super().__init__(f"{waiting_for}: nothing within {timeout:g}s (state {state})")
        self.waiting_for, self.timeout, self.state = waiting_for, timeout, state


class PoolTimeout(WaitTimeout):
    """No free call slot (Limits.max_calls) within Timeouts.pool."""


# -- results: plain views over the core dicts (`raw` keeps everything) --


@dataclass
class Amd:
    result: str  # human, machine, voicemail, sit, silence, unsure
    reason: str
    hints: dict | None  # SIP layer: answer_seconds, ringing, fast_answer, ...
    raw: dict

    @classmethod
    def parse(cls, data):
        return cls(data["result"], data["reason"], data.get("hints"), dict(data))


@dataclass
class Stats:
    codec: str
    remote_rtp: str
    mos: float | None
    rx_packets: int
    tx_packets: int
    rx_lost: int
    rx_loss_percent: float
    jitter_ms: float | None  # RX mean
    rtt_ms: float | None  # mean
    jitter_buffer_ms: int | None  # average delay in the jitter buffer
    raw: dict

    @classmethod
    def parse(cls, streams):
        if not streams:
            return None
        s = max(streams, key=lambda s: (s["generation"], s["media_index"]))
        rx = s["rx"]
        received, lost = rx["packets"], rx["lost_packets"]
        return cls(
            codec=s["codec"],
            remote_rtp=s["remote_rtp"],
            mos=s.get("mos_estimated"),
            rx_packets=received,
            tx_packets=s["tx"]["packets"],
            rx_lost=lost,
            rx_loss_percent=100 * lost / (received + lost) if received + lost else 0.0,
            jitter_ms=(rx.get("jitter_ms") or {}).get("mean"),
            rtt_ms=(s.get("rtt_ms") or {}).get("mean"),
            jitter_buffer_ms=(s.get("jitter_buffer") or {}).get("avg_delay_ms"),
            raw=s,
        )


@dataclass
class Report:
    answered: bool
    code: int | None
    reason: str | None
    connected_seconds: float
    answer_time_seconds: float | None
    amd: Amd | None
    stats: Stats | None
    raw: dict

    @property
    def mos(self):
        return self.stats.mos if self.stats else None

    @classmethod
    def parse(cls, report):
        return cls(
            answered=report.get("answered", False),
            code=report.get("last_sip_code"),
            reason=report.get("last_sip_reason"),
            connected_seconds=report.get("connected_seconds", 0),
            answer_time_seconds=report.get("answer_time_seconds"),
            amd=Amd.parse(report["amd"]) if report.get("amd") else None,
            stats=Stats.parse(report.get("streams")),
            raw=report,
        )
