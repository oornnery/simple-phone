"""What the examples share: accounts of this machine (no PBX) and test audio.

Every example runs on its own: `phone` is account 1001, and the far end is
another account (1002, 1003) of the same endpoint, answered in the same file.
On a real PBX, use `AsyncPhone.from_profile("my-account.json")` and dial
extensions instead.
"""

import array
import math
import random
import tempfile
import wave
from pathlib import Path

from simple_phone import AsyncPhone, Settings

RATE = 8000
FOLDER = Path(tempfile.gettempdir()) / "simple-phone-examples"


def settings(user="1001", rtp_port=40000):
    return Settings(
        server="127.0.0.1",
        user=user,
        account_id=f"local-{user}",
        register=False,
        local_port=5070,
        rtp_port=rtp_port,
        log_level=0,
    )


async def far_end(phone: AsyncPhone, user="1002") -> AsyncPhone:
    """Another account on the same endpoint (RTP ports apart from `phone`)."""
    rtp_port = 40000 + 200 * (int(user) - 1000)
    return await phone.account(settings(user, rtp_port))


def write_wav(name, samples):
    FOLDER.mkdir(exist_ok=True)
    path = FOLDER / name
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(array.array("h", samples).tobytes())
    return str(path)


def tone(hz=440, seconds=1.0, volume=8000):
    count = int(RATE * seconds)
    return [int(volume * math.sin(2 * math.pi * hz * i / RATE)) for i in range(count)]


def speech_like(seconds):
    """Noise at speech level: what the AMD hears as someone talking."""
    rng = random.Random(1)
    return [int(rng.gauss(0, 3000)) for _ in range(int(RATE * seconds))]
