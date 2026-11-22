"""Ouvir: transcrever o que o outro lado fala (Whisper), frase a frase, e
responder com DTMF. Rode antes a URA: python 10_ivr_server.py

    pip install 'simple-phone[stt]'
"""

import asyncio

import local

from simple_phone import AsyncPhone
from simple_phone.media import WhisperSTT

IVR = "sip:1002@127.0.0.1:5072"


async def main():
    stt = WhisperSTT("base", language="pt")  # baixa o modelo na primeira vez
    await stt.load()
    async with AsyncPhone(local.settings(), stt=stt) as phone:
        async with phone.call(IVR) as call:
            print("URA:", await call.listen(timeout=20))
            await call.dtmf("9")  # falar com um atendente
            print("URA:", await call.listen(timeout=15))
            await call.ended(timeout=10)  # a URA desliga
        print("Transcrição:", call.transcript)


asyncio.run(main())
