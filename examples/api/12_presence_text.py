"""Presença, BLF, digitação, texto em tempo real (RTT) e INVITE recusado.

    python 12_presence_text.py

Num PABX, `subscribe(ramal, dialog=True)` também traz Phone.DialogState
(BLF: terminated = livre, early = tocando, confirmed = em chamada). Aqui
não há quem responda SUBSCRIBE de dialog, então só a presença aparece.
"""

import asyncio
from dataclasses import replace

import local

from simple_phone import AsyncPhone, CallFailed


async def main():
    async with AsyncPhone(replace(local.settings(), text=True)) as phone:
        far = await local.far_end(phone)

        # Presença: far observa phone
        @far.on(AsyncPhone.Presence)
        def presence(event):
            print("[far] presença de", event.uri, event.online, event.note)

        @far.on(AsyncPhone.Typing)
        def typing(event):
            print("[far]", event.from_uri, "digitando" if event.typing else "parou")

        await far.subscribe(phone.uri)
        await phone.set_presence(True, "disponível")
        await phone.typing(far.uri)
        await asyncio.sleep(0.5)
        await far.unsubscribe(phone.uri)

        # RTT: os dois lados com Settings(text=True); o texto vai letra a letra
        writer = await phone.account(replace(local.settings("1003", 40600), text=True))

        answered = []

        @phone.on(AsyncPhone.Incoming)
        async def answer(event):
            answered.append(event.call)
            await event.call.answer()

        async with writer.call(phone.uri) as call:
            for char in "olá, mundx\bo":  # \b apaga, como no teclado
                await call.send_text(char)
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.3)
        print("RTT recebido:", repr(answered[0].text_received))

        # INVITE recusado pelo PJSUA antes de virar Call (Require desconhecido)
        @far.on(AsyncPhone.Rejected)
        def rejected(event):
            print("[far] recusado:", event.code, event.reason)

        try:
            async with phone.call(far.uri, headers={"Require": "foo"}):
                pass
        except CallFailed as error:
            print("Chamada:", error)
        await asyncio.sleep(0.2)


asyncio.run(main())
