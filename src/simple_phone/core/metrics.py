"""RTP/RTCP counters from PJSIP turned into plain dicts, plus an estimated MOS."""

from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def millis(stat):
    """PJSIP keeps min/mean/max/last in microseconds. None means no sample."""
    if not stat.n:
        return None
    return {
        key: round(getattr(stat, key) / 1000, 3)
        for key in ("min", "mean", "max", "last")
    }


def direction(stat):
    """RX is measured here. TX loss and jitter come from the peer's RTCP."""
    return {
        "packets": int(stat.pkt),
        "payload_bytes": int(stat.bytes),
        "lost_packets": int(stat.loss),
        "discarded_packets": int(stat.discard),
        "duplicates": int(stat.dup),
        "reordered": int(stat.reorder),
        "jitter_ms": millis(stat.jitterUsec),
        "rtcp_updates": int(stat.updateCount),
    }


def estimate_mos(rx, rtt):
    """Network MOS from the ITU-T G.107 E-model with G.711 parameters.

    Uses loss, jitter and RTT only. It does not listen to the audio, so a
    silent call over a clean network still scores high.
    """
    if not rx["packets"]:
        return None
    loss = 100 * rx["lost_packets"] / (rx["packets"] + rx["lost_packets"])
    jitter = (rx["jitter_ms"] or {}).get("mean", 0)
    delay = (rtt or {}).get("mean", 0) / 2 + 2 * jitter + 40
    r = 93.2 - 0.024 * delay - max(0.0, 0.11 * (delay - 177.3))
    r = max(0.0, min(100.0, r - 95 * loss / (loss + 25.1)))
    return round(min(4.5, 1 + 0.035 * r + r * (r - 60) * (100 - r) * 7e-6), 2)
