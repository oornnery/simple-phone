"""Dialer: many targets in parallel within Limits, and what happens when no
slot is free (PoolTimeout).

Limits(max_calls, calls_per_second) are SIPp's -l and -r: calls up at the
same time, and new calls per second. dial() waits for a slot up to
Timeouts.pool.
"""

import array
import asyncio
import random
import tempfile
import wave
from itertools import count
from pathlib import Path

from simple_phone import AsyncPhone, CallFailed, Limits, PoolTimeout, Timeouts


def greeting_wav(seconds=6, rate=8000):
    """Noise at speech level: what the AMD hears as someone talking."""
    folder = Path(tempfile.gettempdir()) / "simple-phone-examples"
    folder.mkdir(exist_ok=True)
    path = folder / "greeting.wav"
    rng = random.Random(1)
    samples = array.array("h", (int(rng.gauss(0, 3000)) for _ in range(rate * seconds)))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())
    return path


async def classify(call):
    """Runs for each target; dial_all hangs up afterwards."""
    try:
        await call.answered(timeout=5)
    except CallFailed as error:
        return f"{error.code} {error.reason}"
    return (await call.amd(timeout=8)).result


async def main():
    greeting = greeting_wav()
    limits = Limits(max_calls=2, calls_per_second=4)
    async with AsyncPhone(
        server="127.0.0.1", user="1001", register=False, limits=limits
    ) as phone:
        far = await phone.account(user="1002")  # the far end: a second account here
        calls = count(1)

        @far.on(AsyncPhone.Incoming)
        async def answer(event):
            match next(calls) % 3:  # an IVR, a silence, a busy line...
                case 1:
                    await event.call.answer(media="wav", wav=greeting)
                case 2:
                    await event.call.answer()
                case 0:
                    await event.call.reject(486)

        targets = [far.uri] * 3 + ["sip:nobody@127.0.0.1:5999"]
        for target, result in await phone.dial_all(targets, classify):
            print(f"{target:<30} {result}")  # a failure is a result, not an exception

    # One slot, taken: the second call waits Timeouts.pool and gives up.
    limits, timeouts = Limits(max_calls=1), Timeouts(pool=1)
    async with AsyncPhone(
        server="127.0.0.1",
        user="1001",
        register=False,
        limits=limits,
        timeouts=timeouts,
    ) as phone:
        far = await phone.account(user="1002")  # the far end: a second account here
        first = await phone.dial(far.uri)
        try:
            await phone.dial(far.uri)
        except PoolTimeout as error:
            print("No slot:", error)
        await first.hangup()


asyncio.run(main())
