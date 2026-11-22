"""Controle de chamada: espera (hold), conferência, transferência cega e
assistida. Três contas: nós (1001), 1002 e 1003, as duas atendendo em eco."""

import asyncio

import local

from simple_phone import AsyncPhone, Call


async def main():
    async with AsyncPhone(local.settings()) as phone:
        b = await local.far_end(phone, "1002")
        c = await local.far_end(phone, "1003")
        for far in (b, c):

            @far.on(AsyncPhone.Incoming)
            async def answer(event):
                await event.call.answer(media="echo")

            @far.on(Call.TransferRequest)
            def refer(event):
                print(f"[{event.phone.settings.user}] REFER para", event.target)

        # Espera
        async with phone.call(b.uri) as call:
            held = await call.hold()  # volta quando o re-INVITE é respondido
            print("Em espera:", held.status)
            await call.unhold()

        # Conferência e transferência assistida: B passa a falar com C
        async with phone.call(b.uri) as to_b, phone.call(c.uri) as to_c:
            await to_b.conference(to_c)  # B e C se ouvem
            await asyncio.sleep(1)
            await to_b.conference(to_c, enabled=False)
            await to_b.attended_transfer(to_c)  # REFER com Replaces
            status = await to_b.wait_for(Call.TransferStatus, lambda e: e.final)
            print("Assistida:", status.code, status.reason, status.success)
            await to_c.ended(5)  # a perna até C foi substituída
        # ao sair, desligamos a perna até B, como manda o REFER

        # Transferência cega: B liga para C sozinho
        async with phone.call(b.uri) as call:
            await call.transfer(c.uri)
            status = await call.wait_for(Call.TransferStatus, lambda e: e.final)
            print("Cega:", status.code, status.reason, status.success)


asyncio.run(main())
