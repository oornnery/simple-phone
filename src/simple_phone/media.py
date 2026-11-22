"""Audio of a call: frames, sources and sinks, and speech engines.

    await call.send(Echo())                  # what the call transmits
    await call.receive(Speaker(), Recorder("in.wav"))
    async for frame in call.audio(): ...     # AudioFrame
    stream = await call.stream(rate=16000)   # Python-fed source
    await call.say("Olá")                    # TTS through a stream
    text = await call.listen()               # next utterance, via STT

Speech engines are protocols: anything with `async transcribe(pcm, rate)`
(STT) or `synthesize(text)` yielding AudioFrames (TTS). WhisperSTT
(faster-whisper) and PiperTTS (Piper voices) run locally.
"""

from __future__ import annotations

import array
import asyncio
import os
import sys
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AudioFrame:
    """16-bit little-endian mono PCM."""

    pcm: bytes
    rate: int = 8000
    at: float = field(default_factory=time.time)

    @property
    def seconds(self):
        return len(self.pcm) / 2 / self.rate


# -- sources: what a call transmits (call.send) --


@dataclass(frozen=True)
class Silence:
    kind = "silent"


@dataclass(frozen=True)
class Echo:
    kind = "echo"


@dataclass(frozen=True)
class Microphone:
    kind = "mic"


@dataclass(frozen=True)
class WavFile:
    path: str
    loop: bool = False
    kind = "wav"


# -- sinks: where received audio goes (call.receive) --


@dataclass(frozen=True)
class Speaker:
    pass


@dataclass(frozen=True)
class Recorder:
    path: str


class Stream:
    """A source fed from Python, from call.stream(rate). write() never
    blocks; clear() drops what has not played yet (barge-in)."""

    def __init__(self, buffer):
        self._port = buffer  # core StreamBuffer; the native port stays in core
        self.rate = buffer.rate

    def write(self, audio):
        if isinstance(audio, AudioFrame):
            if audio.rate != self.rate:
                raise ValueError(f"frame at {audio.rate} Hz, stream at {self.rate} Hz")
            audio = audio.pcm
        self._port.write(audio)

    def clear(self):
        self._port.clear()

    @property
    def pending(self):
        """Seconds of audio still to play."""
        return self._port.pending()

    async def drain(self):
        while self._port.pending() > 0:
            await asyncio.sleep(0.02)


# -- speech engines --


class STT(Protocol):
    async def transcribe(self, pcm: bytes, rate: int) -> str: ...


class TTS(Protocol):
    def synthesize(self, text: str) -> AsyncIterator[AudioFrame]: ...


def rms(pcm):
    samples = array.array("h", pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    return (sum(x * x for x in samples) / len(samples)) ** 0.5 if samples else 0.0


class Segmenter:
    """Cuts a stream of PCM frames into utterances: speech that ends after
    `end_silence_ms` of quiet. Pure Python, so it can be tested offline."""

    def __init__(
        self,
        rate=8000,
        voice_rms=400,  # same threshold as the AMD detector
        end_silence_ms=700,  # IVR prompts pause ~300-500 ms between phrases
        min_voice_ms=250,  # shorter bursts are clicks, not speech
        max_ms=15000,
        preroll_ms=200,  # keep the start of the first word
    ):
        self.rate = rate
        self.voice_energy = voice_rms * voice_rms
        self.end_silence_ms = end_silence_ms
        self.min_voice_ms = min_voice_ms
        self.max_ms = max_ms
        self.preroll = deque(maxlen=max(1, preroll_ms // 20))
        self.frames = None  # list while collecting an utterance
        self.voice_ms = self.silence_ms = self.total_ms = 0.0

    def feed(self, pcm):
        """One frame in; the finished utterance's PCM out, or None."""
        if not pcm:
            return None
        ms = 1000 * len(pcm) / 2 / self.rate
        voiced = rms(pcm) ** 2 >= self.voice_energy
        if self.frames is None:
            if not voiced:
                self.preroll.append(pcm)
                return None
            self.frames = [*self.preroll, pcm]
            self.preroll.clear()
            self.voice_ms, self.silence_ms, self.total_ms = ms, 0.0, ms
            return None
        self.frames.append(pcm)
        self.total_ms += ms
        if voiced:
            self.voice_ms += ms
            self.silence_ms = 0.0
        else:
            self.silence_ms += ms
        if self.silence_ms >= self.end_silence_ms or self.total_ms >= self.max_ms:
            return self.flush()
        return None

    def flush(self):
        """The utterance in progress, if it is long enough (the audio ended)."""
        frames, self.frames = self.frames, None
        if frames is not None and self.voice_ms >= self.min_voice_ms:
            return b"".join(frames)
        return None


@dataclass
class Utterance:
    text: str
    pcm: bytes  # 16-bit mono at `rate`
    rate: int = 8000
    at: float = field(default_factory=time.time)

    @property
    def seconds(self):
        return len(self.pcm) / 2 / self.rate


async def utterances(call, stt, **segmenter_options):
    """What the other side says, one transcribed utterance at a time, until
    the call ends."""
    segmenter = Segmenter(call.AUDIO_RATE, **segmenter_options)
    async for pcm in _pieces(call, segmenter):
        text = (await stt.transcribe(pcm, call.AUDIO_RATE)).strip()
        if text:
            yield Utterance(text, pcm, call.AUDIO_RATE)


async def _pieces(call, segmenter):
    """Finished utterances, then whatever was being said when the audio
    ended (the other side often hangs up right after speaking)."""
    async for frame in call.audio():
        if (pcm := segmenter.feed(frame.pcm)) is not None:
            yield pcm
    if (pcm := segmenter.flush()) is not None:
        yield pcm


class WhisperSTT:
    """Local speech-to-text, Whisper models via faster-whisper (pip install 'simple-phone[stt]').

    The model loads on first use (or `await stt.load()`). Runs in a worker
    thread, never on the loop. Measured on 8 kHz IVR prompts (4-core CPU,
    int8): "base" ~0.3-0.4 s per second of speech, "small" ~0.7-1.1 s with no
    better accuracy on telephone audio. Keywords still come out wrong now and
    then ("CPF" -> "CTF"): write rules that tolerate it, or use a model-based
    decider.
    """

    def __init__(self, model="base", language="pt", device="cpu", **options):
        self.model_name = model
        self.language = language
        self.device = device
        self.options: dict = {"compute_type": "int8", **options}
        self.model = None

    async def load(self):
        await asyncio.to_thread(self._load)

    def _load(self):
        if self.model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "WhisperSTT needs faster-whisper: pip install 'simple-phone[stt]'"
                ) from exc
            self.model = WhisperModel(
                self.model_name, device=self.device, **self.options
            )
        return self.model

    async def transcribe(self, pcm, rate=8000):
        return await asyncio.to_thread(self._transcribe, pcm, rate)

    def _transcribe(self, pcm, rate):
        import numpy as np  # comes with faster-whisper

        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        if rate != 16000:  # Whisper wants 16 kHz
            positions = np.arange(int(len(audio) * 16000 / rate)) * rate / 16000
            audio = np.interp(positions, np.arange(len(audio)), audio).astype(
                np.float32
            )
        segments, _ = self._load().transcribe(
            audio,
            language=self.language,
            beam_size=1,
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()


class PiperTTS:
    """Local text-to-speech with Piper voices (pip install 'simple-phone[tts]').

    `voice` is a Piper voice name (downloaded once into `voices_dir`, default
    ~/.cache/simple-phone/voices or TTS_VOICES_DIR) or a path to an .onnx
    file. synthesize() yields one AudioFrame per sentence as soon as it is
    ready, so a call can start speaking before the whole text is done.
    """

    def __init__(self, voice="pt_BR-faber-medium", voices_dir=None):
        self.voice_name = voice
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        self.voices_dir = Path(
            voices_dir
            or os.environ.get("TTS_VOICES_DIR")
            or cache / "simple-phone" / "voices"
        )
        self.voice = None

    async def load(self):
        await asyncio.to_thread(self._load)

    def _load(self):
        if self.voice is None:
            try:
                from piper import PiperVoice
                from piper.download_voices import download_voice
            except ImportError as exc:
                raise RuntimeError(
                    "PiperTTS needs Piper: pip install 'simple-phone[tts]'"
                ) from exc
            model = Path(self.voice_name)
            if model.suffix != ".onnx":
                model = self.voices_dir / f"{self.voice_name}.onnx"
                if not model.is_file():
                    self.voices_dir.mkdir(parents=True, exist_ok=True)
                    download_voice(self.voice_name, self.voices_dir)
            self.voice = PiperVoice.load(model)
        return self.voice

    async def synthesize(self, text):
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def work():  # worker thread: Piper is synchronous
            try:
                for chunk in self._load().synthesize(text):
                    frame = AudioFrame(chunk.audio_int16_bytes, chunk.sample_rate)
                    loop.call_soon_threadsafe(queue.put_nowait, frame)
            except Exception as error:  # noqa: BLE001 - re-raised on the loop
                loop.call_soon_threadsafe(queue.put_nowait, error)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        worker = asyncio.ensure_future(asyncio.to_thread(work))
        try:
            while (item := await queue.get()) is not None:
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            await worker
