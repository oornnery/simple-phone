"""Who answered: a person, an IVR, voicemail or an announcement (AMD). For an
IVR, pick an option and record the reply. The far end plays a long greeting."""

import array
import asyncio
import random
import tempfile
import wave
from pathlib import Path

from simple_phone import AsyncPhone

FOLDER = Path(tempfile.gettempdir()) / "simple-phone-examples"
MEANING = {
    "human": "a person (short hello, then waited)",
    "machine": "an IVR or a recorded greeting",
    "voicemail": "voicemail (beep)",
    "sit": "a network announcement (SIT tones)",
    "silence": "nobody spoke",
    "unsure": "no decision",
}


def greeting_wav(seconds=6, rate=8000):
    """Noise at speech level: what the AMD hears as someone talking."""
    FOLDER.mkdir(exist_ok=True)
    path = FOLDER / "greeting.wav"
    rng = random.Random(1)
    samples = array.array("h", (int(rng.gauss(0, 3000)) for _ in range(rate * seconds)))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())
    return path


async def main():
    greeting = greeting_wav()
    answer_file = FOLDER / "option-1.wav"

    async with AsyncPhone(server="127.0.0.1", user="1001", register=False) as phone:
        far = await phone.account(user="1002")  # the far end: a second account here

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
