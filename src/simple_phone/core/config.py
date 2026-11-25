"""Settings of an account and of the endpoint (simple_phone.Settings)."""

from __future__ import annotations

import math
from dataclasses import dataclass

MEDIA_MODES = ("silent", "echo", "wav", "mic")
DTMF_DIGITS = set("0123456789*#ABCD")
PRACK = ("off", "mandatory", "optional")  # in PJSUA_100REL_* order
SESSION_TIMER = ("off", "optional", "required", "always")  # PJSUA_SIP_TIMER_*
CHOICES = {
    "transport": ("udp", "tcp", "tls"),
    "media": MEDIA_MODES,
    "srtp": ("disabled", "optional", "mandatory"),
    "prack": PRACK,
    "session_timer": SESSION_TIMER,
}
RANGES = {  # rtp_port: room for the 100 RTP ports above it
    "max_calls": (1, 64),
    "port": (1, 65535),
    "local_port": (0, 65535),
    "rtp_port": (1024, 65434),
}


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
    speaker: bool = False  # play received audio on the sound card
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
        for name, allowed in CHOICES.items():
            if getattr(self, name) not in allowed:
                raise ValueError(f"{name} must be one of {', '.join(allowed)}")
        for name, (low, high) in RANGES.items():
            if not low <= getattr(self, name) <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
        if self.rtp_port % 2:
            raise ValueError("rtp_port must be even")
        if self.turn_server and not self.ice:
            raise ValueError("TURN requires ICE")
        if not math.isfinite(self.stats_interval) or self.stats_interval <= 0:
            raise ValueError("stats_interval must be positive and finite")

    def uri(self, target):
        """'1002' becomes sip:1002@domain, '1002@host' sip:1002@host; a
        sip: URI is kept as is."""
        if target.startswith(("sip:", "sips:")):
            return target
        if "@" in target:
            return f"sip:{target}"
        return f"sip:{target}@{self.domain}"
