"""Who answered: a person, an IVR, voicemail or an announcement (AMD). For an
IVR, pick an option and record the reply. The far end plays a long greeting."""

import asyncio

import local

from simple_phone import AsyncPhone

MEANING = {
    "human": "a person (short hello, then waited)",
    "machine": "an IVR or a recorded greeting",
    "voicemail": "voicemail (beep)",
    "sit": "a network announcement (SIT tones)",
    "silence": "nobody spoke",
    "unsure": "no decision",
}


async def main():
    greeting = local.write_wav("greeting.wav", local.speech_like(6))
    answer_file = local.FOLDER / "option-1.wav"

    async with AsyncPhone(local.settings()) as phone:
        far = await local.far_end(phone)

        @far.on(AsyncPhone.Incoming)
        async def ivr(event):
            await event.call.answer(media="wav", wav=greeting)

        async with phone.call(far.uri) as call:
            # settle: after "machine", keep listening a little for a beep.
            amd = await call.amd(timeout=10, settle=1)
            print("Answered by:", MEANING[amd.result], f"({amd.reason})")
            print("SIP hints:", amd.hints)
            if amd.result == "machine":
                await call.dtmf("1")
                await call.record(answer_file)
                await asyncio.sleep(2)
                await call.record(None)
                print("Reply to option 1 recorded in", answer_file)


asyncio.run(main())
