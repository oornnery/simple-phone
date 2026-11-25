import asyncio
import tempfile
import unittest
import wave
from pathlib import Path

from simple_phone import AsyncPhone, Settings
from simple_phone.media import AudioFrame, Segmenter, noise, rms, save_wav, silence

RATE, FRAME = 8000, 320  # FRAME: bytes in 20 ms


class SegmenterTest(unittest.TestCase):
    def test_splits_on_pauses_and_drops_clicks(self):
        audio = noise(0.9) + silence(0.3) + noise(0.4) + silence(0.9)
        audio += noise(0.1) + silence(0.9)  # a click: too short
        audio += noise(0.6, seed=2) + silence(0.9)
        segmenter = Segmenter()
        found = []
        for i in range(0, len(audio), FRAME):
            if piece := segmenter.feed(audio[i : i + FRAME]):
                found.append(len(piece) / 2 / RATE)
        self.assertEqual(len(found), 2)  # the 300 ms pause did not split
        # speech, the short pause, speech, then the 700 ms of silence that ended it
        self.assertAlmostEqual(found[0], 0.9 + 0.3 + 0.4 + 0.7, delta=0.05)


class FlushTest(unittest.TestCase):
    def test_the_last_utterance_is_kept_when_the_audio_ends(self):
        segmenter = Segmenter()
        audio = noise(0.6)  # speech, then the call ends: no closing silence
        for i in range(0, len(audio), FRAME):
            self.assertIsNone(segmenter.feed(audio[i : i + FRAME]))
        self.assertAlmostEqual(len(segmenter.flush()) / 2 / RATE, 0.6, delta=0.03)
        self.assertIsNone(segmenter.flush())


class FakeTTS:
    def __init__(self, seconds=1.5, rate=16000):
        self.seconds, self.rate, self.said = seconds, rate, []

    async def synthesize(self, text):
        self.said.append(text)
        pcm = noise(self.seconds, rate=self.rate)
        half = len(pcm) // 4 * 2  # two "sentences", like Piper
        yield AudioFrame(pcm[:half], self.rate)
        yield AudioFrame(pcm[half:], self.rate)


class FakeSTT:
    async def transcribe(self, audio, rate):
        return f"{len(audio) / 2 / rate:.1f}s of speech"


def local(user, account_id, rtp_port):
    return Settings(
        server="127.0.0.1",
        user=user,
        account_id=account_id,
        register=False,
        local_port=5098,
        rtp_port=rtp_port,
        log_level=0,
    )


async def loudness(call, seconds=0.6):
    """Mean RMS of what `call` receives over `seconds`."""
    values = []
    try:
        async with asyncio.timeout(seconds):
            async for frame in call.audio():
                values.append(rms(frame.pcm))
    except TimeoutError:
        pass
    return sum(values) / len(values) if values else 0.0


class MediaTest(unittest.IsolatedAsyncioTestCase):
    """Two accounts on one local endpoint: `phone` calls `other`."""

    async def asyncSetUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.noise = self.folder / "noise.wav"
        save_wav(self.noise, noise(3))
        self.tts = FakeTTS()
        self.phone = AsyncPhone(local("1001", "a", 47400), tts=self.tts, stt=FakeSTT())
        await self.phone.__aenter__()
        self.addAsyncCleanup(self.phone.close)
        self.other = await self.phone.account(local("1002", "b", 47600))
        self.incoming = None

        @self.other.on(AsyncPhone.Incoming)
        async def answer(event):
            self.incoming = event.call
            await event.call.answer()

    async def test_send_switches_the_source_while_the_call_runs(self):
        async with self.phone.call(self.other.uri) as call:
            self.assertLess(await loudness(self.incoming), 50)  # silent by default
            await call.send("wav", self.noise, loop=True)
            self.assertGreater(await loudness(self.incoming), 1000)
            await call.send("silent")
            await asyncio.sleep(0.2)
            self.assertLess(await loudness(self.incoming), 50)
            await self.incoming.send("wav", self.noise)
            await call.send("echo")  # what comes in goes back out
            self.assertGreater(await loudness(self.incoming), 1000)

    async def test_receive_records_and_stream_feeds_python_audio(self):
        recorded = self.folder / "in.wav"
        async with self.phone.call(self.other.uri) as call:
            await self.incoming.record(recorded)
            stream = await call.stream(rate=16000)
            stream.write(noise(1, rate=16000))
            self.assertGreater(await loudness(self.incoming, 0.5), 1000)
            stream.clear()  # drops the rest
            await asyncio.sleep(0.2)
            self.assertLess(await loudness(self.incoming, 0.4), 50)
            self.assertEqual(stream.pending, 0)
            await self.incoming.record(None)  # stop recording
        with wave.open(str(recorded)) as audio:
            self.assertGreater(audio.getnframes(), RATE // 4)

    async def test_say_speaks_and_stops_when_interrupted(self):
        async with self.phone.call(self.other.uri) as call:
            hearing = asyncio.ensure_future(loudness(self.incoming, 1.0))
            self.assertTrue(await call.say("segunda via"))
            self.assertGreater(await hearing, 500)
            self.assertEqual(self.tts.said, ["segunda via"])

            self.tts.seconds = 6  # long speech, and the other side talks over it
            await self.incoming.send("wav", self.noise, loop=True)
            started = asyncio.get_running_loop().time()
            self.assertFalse(await call.say("um texto longo", interrupt=True))
            self.assertLess(asyncio.get_running_loop().time() - started, 3)

    async def test_gather_listen_and_inband_dtmf(self):
        async with self.phone.call(self.other.uri) as call:
            gathering = asyncio.ensure_future(self.incoming.gather(timeout=5))
            await asyncio.sleep(0.2)
            await call.dtmf("12#")
            self.assertEqual(await gathering, "12")

            gathering = asyncio.ensure_future(self.incoming.gather(length=2, timeout=5))
            await asyncio.sleep(0.2)
            await call.dtmf("789")
            self.assertEqual(await gathering, "78")

            await asyncio.sleep(0.6)  # the 9 left over arrives
            self.assertEqual(await self.incoming.gather(timeout=0.3), "")  # nothing

            save_wav(self.noise, silence(0.2) + noise(0.8) + silence(1.5))
            listening = asyncio.ensure_future(call.listen(timeout=5))
            await self.incoming.send("wav", self.noise)
            self.assertRegex(await listening, r"s of speech$")

            hearing = asyncio.ensure_future(loudness(self.incoming, 0.8))
            await call.dtmf("5", method="inband")  # tones inside the audio
            self.assertGreater(await hearing, 100)


if __name__ == "__main__":
    unittest.main()
