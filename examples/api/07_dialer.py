"""Discador: vários destinos em paralelo dentro dos Limits, e o que acontece
quando não há vaga (PoolTimeout).

Limits(max_calls, calls_per_second) são o -l e o -r do SIPp: chamadas
discadas ao mesmo tempo e novas por segundo. dial() espera vaga até
Timeouts.pool.
"""

import asyncio
from itertools import count

import local

from simple_phone import AsyncPhone, CallFailed, Limits, PoolTimeout, Timeouts


async def classify(call):
    """Roda para cada destino; dial_all desliga depois."""
    try:
        await call.answered(timeout=5)
    except CallFailed as error:
        return f"{error.code} {error.reason}"
    return (await call.amd(timeout=8)).result


async def main():
    greeting = local.write_wav("saudacao.wav", local.speech_like(6))
    limits = Limits(max_calls=2, calls_per_second=4)
    async with AsyncPhone(local.settings(), limits=limits) as phone:
        far = await local.far_end(phone)
        calls = count(1)

        @far.on(AsyncPhone.Incoming)
        async def answer(event):
            match next(calls) % 3:  # uma URA, um silêncio, um ocupado...
                case 1:
                    await event.call.answer(media="wav", wav=greeting)
                case 2:
                    await event.call.answer()
                case 0:
                    await event.call.reject(486)

        targets = [far.uri] * 3 + ["sip:ninguem@127.0.0.1:5999"]
        for target, result in await phone.dial_all(targets, classify):
            print(f"{target:<30} {result}")  # falha vira resultado, não exceção

    # Uma vaga só, ocupada: a segunda chamada espera Timeouts.pool e desiste.
    limits, timeouts = Limits(max_calls=1), Timeouts(pool=1)
    async with AsyncPhone(local.settings(), limits=limits, timeouts=timeouts) as phone:
        far = await local.far_end(phone)
        first = await phone.dial(far.uri)
        try:
            await phone.dial(far.uri)
        except PoolTimeout as error:
            print("Sem vaga:", error)
        await first.hangup()


asyncio.run(main())
