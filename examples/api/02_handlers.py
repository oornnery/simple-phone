"""Receber chamadas e reagir a eventos, de três jeitos:

1. métodos on_<grupo>_<evento> numa subclasse (como o Textual);
2. @phone.on(Tipo, atributo=valor), com filtro;
3. async for event in phone.events(Tipo): um fluxo.

Num ramal de verdade, troque o final por `await ramal.serve()` (até Ctrl+C).
"""

import asyncio

import local

from simple_phone import AsyncPhone, Call


class Ramal(AsyncPhone):
    async def on_phone_incoming(self, event):
        print("[ramal] chamada de", event.remote_uri)
        await event.call.answer(183)  # early media: áudio antes de atender
        await asyncio.sleep(0.5)
        await event.call.answer(media="echo")

    def on_call_dtmf(self, event):
        print("[ramal] digitou", event.digit, f"({event.method})")

    def on_call_ended(self, event):
        print("[ramal] fim:", event.report.code, event.report.reason)


async def main():
    async with Ramal(local.settings("1002", 40200)) as ramal:
        phone = await ramal.account(local.settings("1001", 40000))

        @ramal.on(Call.Dtmf, digit="#")  # só o '#'
        async def hang_up(event):
            await event.call.hangup()

        async def show_states():
            async for event in phone.events(Call.StateChanged):
                print("[quem liga] estado:", event.state, event.code)

        watcher = asyncio.create_task(show_states())
        call = await phone.dial(ramal.uri)
        await call.answered()
        await call.dtmf("12#")
        report = await call.ended(timeout=10)  # o ramal desliga no '#'
        print("Atendida:", report.answered, "| fluxo:", " ".join(call.trace.flow()))
        watcher.cancel()


asyncio.run(main())
