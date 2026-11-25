"""Listening: transcribe what the far end says (Whisper), sentence by
sentence, and answer with DTMF. Start the IVR first: python 10_ivr_server.py

    pip install 'simple-phone[stt]'
"""

import asyncio

from simple_phone import AsyncPhone
from simple_phone.media import WhisperSTT

IVR = "sip:1002@127.0.0.1:5072"


async def main():
    stt = WhisperSTT("base")  # English; downloads the model the first time
    await stt.load()
    async with AsyncPhone(
        server="127.0.0.1", user="1001", register=False, stt=stt
    ) as phone:
        async with phone.call(IVR) as call:
            print("IVR:", await call.listen(timeout=20))
            await call.dtmf("9")  # talk to an agent
            print("IVR:", await call.listen(timeout=15))
            await call.ended(timeout=10)  # the IVR hangs up
        print("Transcript:", call.transcript)


asyncio.run(main())
