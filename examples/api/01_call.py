"""Ligar: chamada com escopo, DTMF, relatório, ocupado e o controle passo a passo."""

import asyncio

import local

from simple_phone import AsyncPhone, CallFailed


async def main():
    async with AsyncPhone(local.settings()) as phone:
        far = await local.far_end(phone)
        busy = False

        @far.on(AsyncPhone.Incoming)
        async def answer(event):
            if busy:
                await event.call.reject(486)
            else:
                await event.call.answer(media="echo")

        # 1. Com escopo: atendida ao entrar (ou CallFailed), desligada ao sair.
        async with phone.call(far.uri) as call:
            print("Respostas:", [m.label for m in call.history])
            await call.dtmf("1234#")
            await asyncio.sleep(2)
            print(f"Conectada há {call.duration:.1f}s")
        report = call.report
        print(f"Relatório: {report.code} {report.reason}, MOS {report.mos}")

        # 2. Recusada: CallFailed traz o código SIP.
        busy = True
        try:
            async with phone.call(far.uri):
                pass
        except CallFailed as error:
            print("Recusada:", error.code, error.reason)

        # 3. Sem escopo: cada passo é seu.
        busy = False
        call = await phone.dial(far.uri)  # volta logo, ainda tocando
        await call.answered(timeout=10)
        report = await call.hangup()
        print("Passo a passo:", report.answered, report.code)


asyncio.run(main())
