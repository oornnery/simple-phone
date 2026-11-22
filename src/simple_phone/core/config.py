"""Settings of an account and of the endpoint (simple_phone.Settings)."""

from __future__ import annotations

import math
from dataclasses import dataclass

MEDIA_MODES = ("silent", "echo", "wav", "mic")
DTMF_DIGITS = set("0123456789*#ABCD")
PRACK = ("off", "mandatory", "optional")  # in PJSUA_100REL_* order
SESSION_TIMER = ("off", "optional", "required", "always")  # PJSUA_SIP_TIMER_*


@dataclass
class Config:
    # account
    server: str
    user: str
    port: int = 5060
    auth_user: str | None = None
    domain: str | None = None
    proxy: str | None = None
    register: bool = True
    auto_register: bool = True
    account_id: str = "default"
    # media
    media: str = "silent"
    wav: str = "reference.wav"
    wav_loop: bool = False
    listen: bool = False
    record: str | None = None
    codec: str = "auto"
    capture_device: int | None = None
    playback_device: int | None = None
    ec_tail: int = 200
    amd: bool = True  # classify outgoing calls: human, IVR, announcement
    follow_redirects: bool = False  # 3xx: follow the new target, as httpx does
    accept_transfers: bool = True  # REFER received: accept (202) or decline (603)
    prack: str = "off"  # 100rel (RFC 3262): off, optional, mandatory
    session_timer: str = "off"  # RFC 4028: off, optional, required, always
    text: bool = False  # RTT (RFC 4103): offer a T.140 text stream
    mwi: bool = False  # SUBSCRIBE to message-summary: voicemail as Phone.Mwi
    # network and timing
    local_port: int = 5070
    rtp_port: int = 40000
    log_level: int = 3
    stats_interval: float = 1
    transport: str = "udp"
    bind_address: str = ""
    public_address: str = ""
    stun_servers: tuple[str, ...] = ()
    ice: bool = False
    turn_server: str = ""
    turn_user: str = ""
    turn_password: str = ""
    tls_ca_file: str = ""
    tls_verify: bool = True
    srtp: str = "disabled"
    max_calls: int = 1

    def __post_init__(self):
        self.domain = self.domain or self.server
        if not self.server or not self.user:
            raise ValueError("server and user are required")
        if self.transport not in ("udp", "tcp", "tls"):
            raise ValueError("transport must be udp, tcp or tls")
        if self.media not in MEDIA_MODES:
            raise ValueError("invalid media mode")
        if self.srtp not in ("disabled", "optional", "mandatory"):
            raise ValueError("invalid SRTP policy")
        if self.prack not in PRACK:
            raise ValueError(f"prack must be one of {', '.join(PRACK)}")
        if self.session_timer not in SESSION_TIMER:
            raise ValueError(f"session_timer must be one of {', '.join(SESSION_TIMER)}")
        if self.turn_server and not self.ice:
            raise ValueError("TURN requires ICE")
        if not 1 <= self.max_calls <= 64:
            raise ValueError("max_calls must be between 1 and 64")
        if not math.isfinite(self.stats_interval) or self.stats_interval <= 0:
            raise ValueError("stats_interval must be positive and finite")
        if not 1 <= self.port <= 65535 or not 0 <= self.local_port <= 65535:
            raise ValueError("invalid SIP port")
        if not 1024 <= self.rtp_port <= 65434 or self.rtp_port % 2:
            raise ValueError("rtp_port must be even and between 1024 and 65434")

    def uri(self, target):
        """'1002' becomes sip:1002@domain; a sip: URI is kept as is."""
        if target.startswith(("sip:", "sips:")):
            return target
        return f"sip:{target}@{self.domain}"
