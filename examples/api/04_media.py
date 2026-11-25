"""Media: what the call sends and where the received audio goes, live audio
in Python, RTP statistics and the three kinds of DTMF.

Send: send("silent" | "echo" | "mic"), or send("wav", file, loop=...).
Receive: record(file) saves it; speaker() plays it on the sound card. With a
sound card, use send("mic") and speaker() to talk for real.
"""

import array
import asyncio
import math
import tempfile
import wave
from pathlib import Path

from simple_phone import AsyncPhone, Call
from simple_phone.media import AudioFrame, rms

FOLDER = Path(tempfile.gettempdir()) / "simple-phone-examples"


def tone(hz, seconds, rate=8000):
    """A sine wave as 16-bit mono PCM."""
    count = int(rate * seconds)
    wave_ = (int(8000 * math.sin(2 * math.pi * hz * i / rate)) for i in range(count))
    return array.array("h", wave_).tobytes()


def save_wav(name, pcm, rate=8000):
    FOLDER.mkdir(exist_ok=True)
    path = FOLDER / name
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)
    return path


async def main():
    beep = save_wav("beep.wav", tone(880, 0.3))
    music = save_wav("tone.wav", tone(440, 1.0))
    received = FOLDER / "received.wav"

    async with AsyncPhone(server="127.0.0.1", user="1001", register=False) as phone:
        far = await phone.account(user="1002")  # the far end: a second account here

        @far.on(AsyncPhone.Incoming)
        async def answer(event):
            await event.call.answer(media="echo")  # sends back what it hears

        @far.on(Call.Dtmf)
        def digit(event):
            print("[far end] DTMF", event.digit, f"({event.method})")

        async with phone.call(far.uri) as call:
            await call.send("wav", music, loop=True)  # what we transmit
            await call.record(received)  # records what we hear

            frames = []
            async for frame in call.audio():  # received PCM, 20 ms per frame
                frames.append(frame)
                if len(frames) == 50:
                    break
            loudest = max(rms(f.pcm) for f in frames)
            print(f"Live audio: {len(frames)} frames, peak RMS {loudest:.0f}")

            async for stats in call.stats():  # every stats_interval (1 s)
                print(
                    f"RTP: {stats.codec}, {stats.rx_packets} packets, loss"
                    f" {stats.rx_loss_percent:.1f}%, jitter {stats.jitter_ms} ms,"
                    f" buffer {stats.jitter_buffer_ms} ms, MOS {stats.mos}"
                )
                break

            await call.send("silent")
            await call.play(beep)  # plays on top and returns when done
            stream = await call.stream()  # a source fed from Python
            stream.write(AudioFrame(tone(660, 0.3)))
            await stream.drain()

            await call.gain(microphone=0.5, speaker=1.0)
            await call.mute()
            await call.mute(False)

            await call.dtmf("1", method="rfc4733")  # RTP events (the default)
            await call.dtmf("2", method="info")  # SIP INFO
            await call.dtmf(
                "3", method="inband"
            )  # tones in the audio (PJSUA does not detect them)
            await asyncio.sleep(1)
            await call.record(None)  # stops recording

        print("Recorded:", received)


asyncio.run(main())
