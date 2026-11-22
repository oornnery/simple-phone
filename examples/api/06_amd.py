"""Quem atendeu: pessoa, URA, caixa postal ou anúncio (AMD); e, sendo URA,
escolher uma opção e gravar a resposta. O outro lado toca uma saudação longa."""

import asyncio

import local

from simple_phone import AsyncPhone

MEANING = {
    "human": "pessoa (alô curto, depois esperou)",
    "machine": "URA ou saudação gravada",
    "voicemail": "caixa postal (bipe)",
    "sit": "anúncio da operadora (tons SIT)",
    "silence": "ninguém falou",
    "unsure": "não deu para decidir",
}


async def main():
    greeting = local.write_wav("saudacao.wav", local.speech_like(6))
    answer_file = local.FOLDER / "opcao-1.wav"

    async with AsyncPhone(local.settings()) as phone:
        far = await local.far_end(phone)

        @far.on(AsyncPhone.Incoming)
        async def ivr(event):
            await event.call.answer(media="wav", wav=greeting)

        async with phone.call(far.uri) as call:
            # settle: depois de "machine", escuta mais um pouco por um bipe.
            amd = await call.amd(timeout=10, settle=1)
            print("Atendeu:", MEANING[amd.result], f"({amd.reason})")
            print("Dicas SIP:", amd.hints)
            if amd.result == "machine":
                await call.dtmf("1")
                await call.record(answer_file)
                await asyncio.sleep(2)
                await call.record(None)
                print("Resposta da opção 1 gravada em", answer_file)


asyncio.run(main())
