"""Dialer: many targets in parallel within Limits, and what happens when no
slot is free (PoolTimeout).

Limits(max_calls, calls_per_second) are SIPp's -l and -r: calls up at the
same time, and new calls per second. dial() waits for a slot up to
Timeouts.pool.
"""

import asyncio
from itertools import count

import local

from simple_phone import AsyncPhone, CallFailed, Limits, PoolTimeout, Timeouts


async def classify(call):
    """Runs for each target; dial_all hangs up afterwards."""
    try:
        await call.answered(timeout=5)
    except CallFailed as error:
        return f"{error.code} {error.reason}"
    return (await call.amd(timeout=8)).result


async def main():
    greeting = local.write_wav("greeting.wav", local.speech_like(6))
    limits = Limits(max_calls=2, calls_per_second=4)
    async with AsyncPhone(local.settings(), limits=limits) as phone:
        far = await local.far_end(phone)
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
    async with AsyncPhone(local.settings(), limits=limits, timeouts=timeouts) as phone:
        far = await local.far_end(phone)
        first = await phone.dial(far.uri)
        try:
            await phone.dial(far.uri)
        except PoolTimeout as error:
            print("No slot:", error)
        await first.hangup()


asyncio.run(main())
