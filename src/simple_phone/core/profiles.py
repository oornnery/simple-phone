"""Personal profiles are plain JSON. Credentials are referenced by env name."""

import json
from dataclasses import fields, replace
from pathlib import Path

from .config import Config

ENDPOINT_FIELDS = {
    "local_port",
    "transport",
    "bind_address",
    "public_address",
    "stun_servers",
    "tls_ca_file",
    "tls_verify",
    "codec",
    "capture_device",
    "playback_device",
    "ec_tail",
    "max_calls",
    "log_level",
    "stats_interval",
}


def load_profile(path):
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = {f.name for f in fields(Config)} | {"password_env"}
    if not isinstance(profile, dict) or set(profile) - allowed:
        raise ValueError("Profile contains unknown settings")
    if "password_env" in profile and not isinstance(profile["password_env"], str):
        raise ValueError("password_env must be an environment variable name")
    return profile


def load_account(path, base: Config, index: int = 1) -> tuple[Config, str]:
    """Another SIP identity on the same endpoint, with its own RTP range/media."""
    values = load_profile(path)
    password_env = values.pop("password_env", "SIP_PASSWORD")
    values.setdefault("account_id", Path(path).stem)
    values.setdefault("rtp_port", base.rtp_port + 200 * index)
    # A different identity must not silently reuse the main account's login
    # or routing. Media/device defaults can still be inherited.
    values.setdefault("auth_user", None)
    if values.get("server", base.server) != base.server:
        values.setdefault("domain", None)
        values.setdefault("proxy", None)
        values.setdefault("port", 5060)
    # The endpoint validates the rest when it opens the account.
    return replace(base, **values), password_env
