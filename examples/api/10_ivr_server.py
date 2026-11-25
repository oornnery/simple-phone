"""An IVR on the answering side: speaks with Piper and reads the keypad.

    pip install 'simple-phone[tts]'
    python 10_ivr_server.py        # SIP port 5072; Ctrl+C quits

Call sip:1002@127.0.0.1:5072 from another terminal (11_listen.py or a
softphone). say(interrupt=True) stops talking as soon as the caller talks
(barge-in).
"""

import asyncio
import contextlib

from simple_phone import AsyncPhone, Settings
from simple_phone.media import PiperTTS

MENU = "Hello. For a copy of your bill, press 1. To talk to an agent, press 9."


async def ivr(event):
    call = event.call
    await call.answer()
    await asyncio.sleep(0.5)
    for _ in range(3):
        await call.say(MENU, interrupt=True)
        match await call.gather(length=1, timeout=6):
            case "1":
                await call.say("Enter your account number, then press the pound key.")
                account = await call.gather(finish_on="#", timeout=20)
                print("Account number:", account)
                await call.say(
                    "Done. The copy of your bill was sent by email. Thank you."
                )
                break
            case "9":
                await call.say("Transferring you to an agent.")
                break
            case "":
                await call.say("I did not get an option.")
            case _:
                await call.say("Invalid option.")
    await call.hangup()


async def main():
    settings = Settings(
        server="127.0.0.1", user="1002", register=False, local_port=5072, rtp_port=42000
    )
    tts = PiperTTS("en_US-lessac-medium")
    await tts.load()
    async with AsyncPhone(settings, tts=tts) as phone:
        phone.on(AsyncPhone.Incoming)(ivr)
        print("IVR at", phone.uri, "(Ctrl+C quits)")
        await phone.serve()


with contextlib.suppress(KeyboardInterrupt):
    asyncio.run(main())
