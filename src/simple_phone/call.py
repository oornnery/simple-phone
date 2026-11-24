"""One call of an AsyncPhone: actions, typed waits and live streams."""

from __future__ import annotations

import asyncio
import time
import wave
from dataclasses import replace

from .core.call import Call as Native
from .events import CallEvents
from .media import AudioFrame, Stream, rms, utterances
from .models import CallFailed, PhoneError, Report, WaitTimeout


class Trace(list):
    """The SIP messages of a call, in order."""

    def flow(self):
        """['INVITE', '100', '180', '200', 'ACK', 'BYE', '200']"""
        return [m.method if m.is_request else str(m.code) for m in self]


class Call(CallEvents):
    """One call. Get it from phone.dial(), phone.call(), or Phone.Incoming."""

    AUDIO_RATE = 8000  # call.audio(): 16-bit mono PCM, 20 ms frames

    def __init__(self, phone, ref, incoming=False):
        self.phone = phone
        self.ref = ref
        self.incoming = incoming
        self.destination = None  # the URI dialed, for outgoing calls
        self.call_id = self.remote_uri = self.state = None
        self.code, self.reason = None, ""  # last SIP status
        self.answered_at = None
        self.timeline = []  # every typed event of this call, in order
        self.transcript = []  # (speaker, text): "local" said, "remote" heard
        self.report: Report | None = None  # set when the call is over
        # wait_for(Call.Sip) twice finds two messages: each event type resumes
        # after its own previous match, without hiding other types.
        self._cursors = {}
        self._audio_queues = set()
        self._streams = {}  # rate -> Stream used by say()
        self._changed = asyncio.Event()

    def __repr__(self):
        return f"<Call {self.ref} {self.state} {self.remote_uri or self.destination}>"

    # -- what happened --

    @property
    def trace(self):
        return Trace(e.message for e in self.timeline if isinstance(e, self.Sip))

    @property
    def history(self):
        """Responses received to our INVITE: provisional ones, then the final."""
        return [
            m
            for m in self.trace
            if m.direction == "RX" and not m.is_request and m.cseq_method == "INVITE"
        ]

    @property
    def response(self):
        """The final response to our INVITE (>= 200), once it arrived."""
        return next((m for m in reversed(self.history) if m.code >= 200), None)

    @property
    def text_received(self):
        """RTT received so far (Call.Text), with backspaces applied."""
        chars = []
        for event in self.timeline:
            if isinstance(event, self.Text):
                for char in event.text:
                    if char == "\b":
                        if chars:
                            chars.pop()
                    else:
                        chars.append(char)
        return "".join(chars)

    @property
    def dtmf_sent(self):
        return "".join(e.digits for e in self.timeline if isinstance(e, self.DtmfSent))

    @property
    def dtmf_received(self):
        return "".join(e.digit for e in self.timeline if isinstance(e, self.Dtmf))

    def _push(self, event):
        self.timeline.append(event)
        self.call_id = event.call_id or self.call_id
        # StateChanged and Phone.Incoming carry it
        self.remote_uri = getattr(event, "remote_uri", None) or self.remote_uri
        if isinstance(event, self.StateChanged):
            self.state, self.code, self.reason = event.state, event.code, event.reason
            if self.state == "CONFIRMED" and self.answered_at is None:
                self.answered_at = event.at
            if self.state == "DISCONNECTED":
                for queue in self._audio_queues:
                    queue.put_nowait(None)  # ends every call.audio() stream
        elif isinstance(event, self.Ended):
            self.report = event.report
        self._changed.set()

    def emit(self, event):
        """Add an event of your own (a CallEvent) to this call: it lands in
        the timeline, wait_for(), events() and the phone's handlers."""
        event = replace(event, phone=self.phone, call=self, ref=self.ref)
        self._push(event)
        self.phone._push(event)

    async def _do(self, action, *args, live=True):
        """action(core call, *args) on the engine thread; Call arguments
        become their core calls. live=False: no error if the call is over."""
        calls = self.phone._endpoint.calls

        def native(call):
            found = calls.get(call.ref)
            if found is None or found.ended_at:
                raise RuntimeError("The call has ended")
            return found

        def run():
            if not live and self.ref not in calls:
                return None
            values = [native(a) if isinstance(a, Call) else a for a in args]
            return action(native(self) if live else calls[self.ref], *values)

        return await self.phone._run(run)

    @property
    def duration(self):
        """Seconds connected so far; final once the call is over."""
        if self.report is not None:
            return self.report.connected_seconds
        return time.time() - self.answered_at if self.answered_at else 0.0

    # -- actions --

    async def answer(self, code=200, **media):
        """Answer (1xx keeps it ringing, e.g. 183). `media`: media, wav,
        speaker, record for this call only, e.g. answer(media="echo")."""
        if media:
            await self._do(Native.configure, media)
        await self._do(Native.accept, code)

    async def reject(self, code=486):
        await self._do(Native.reject, code)

    async def hangup(self, timeout=10) -> Report:
        """Hang up (or decline) and wait for the final report."""
        if self.report is None:
            try:
                await self._do(Native.end)
            except PhoneError:
                if self.report is None and self.state != "DISCONNECTED":
                    raise  # not just a race with the far end hanging up
        return await self.ended(timeout)

    async def dtmf(self, digits, method="rfc4733"):
        """Send DTMF: rfc4733 (RTP events), info (SIP INFO) or inband (tones
        in the audio itself)."""
        await self._do(Native.send_dtmf, digits, method)

    async def hold(self, timeout=None):
        """Put the far end on hold. Returns the Call.MediaChanged that
        confirms it, once the re-INVITE is answered."""
        return await self._then(
            Native.hold, (), self.MediaChanged, lambda e: e.held, timeout
        )

    async def unhold(self, timeout=None):
        return await self._then(
            Native.unhold, (), self.MediaChanged, lambda e: not e.held, timeout
        )

    async def transfer(self, target):
        """Blind transfer (REFER); progress arrives as Call.TransferStatus."""
        await self._do(Native.transfer, target)

    async def attended_transfer(self, other):
        """Transfer the far end of this call to the far end of `other`
        (REFER with Replaces); progress arrives as Call.TransferStatus.
        `other` ends when replaced; hang this call up after success."""
        await self._do(Native.transfer_to, other)

    async def conference(self, other, enabled=True):
        """Mix this call's audio with `other` (both far ends hear each other)."""
        await self._do(Native.conference, other, enabled)

    async def send_text(self, text):
        """RTT (RFC 4103): send `text` as typed ("\b" erases). Needs
        Settings(text=True) on both sides; arrives there as Call.Text."""
        await self._do(Native.send_text, text)

    async def dump(self, media=True):
        """PJSUA's text dump of the call: dialog, SDP and per-stream media."""
        return await self._do(Native.describe, media)

    async def mute(self, enabled=True):
        await self._do(Native.mute, enabled)

    async def gain(self, microphone=1.0, speaker=1.0):
        await self._do(Native.gain, microphone, speaker)

    async def record(self, path=None):
        """Record received audio to `path`; None stops."""
        await self._do(Native.set_recording, str(path) if path else None)

    async def play(self, path):
        """Send a WAV to the other side (mixed with the call's media) and
        return when it has played, or when the call ends."""
        with wave.open(str(path), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
        token = await self._do(Native.play, str(path))
        try:
            await self.ended(timeout=seconds + 0.2)  # returns early on hangup
        except WaitTimeout:
            pass  # played to the end
        finally:
            if self.report is None:
                try:
                    await self._do(Native.stop_play, token, live=False)
                except PhoneError:
                    pass

    # -- media --

    async def send(self, media, wav=None, *, loop=False):
        """Change what the call transmits: "silent", "echo", "mic", or
        "wav" with a file, e.g. send("wav", "notice.wav", loop=True).
        Streams, play() and say() mix on top of it."""
        await self._do(Native.set_source, media, str(wav) if wav else None, loop)

    async def speaker(self, enabled=True):
        """Play received audio on the sound card (or stop)."""
        await self._do(Native.set_speaker, enabled)

    async def stream(self, rate=8000) -> Stream:
        """A source fed from Python (16-bit mono PCM at `rate`), mixed into
        what the call transmits."""
        if rate not in self._streams:
            port = await self._do(Native.open_stream, rate)
            self._streams[rate] = Stream(port)
        return self._streams[rate]

    async def say(self, text, *, tts=None, interrupt=False):
        """Speak `text` (TTS, sentence by sentence as it is synthesized).
        With interrupt=True, stop as soon as the other side starts talking.
        Returns True if everything was said."""
        tts = tts or self.phone.tts
        if tts is None:
            raise PhoneError("say() needs a TTS: AsyncPhone(..., tts=PiperTTS())")
        talking = asyncio.ensure_future(self._speech_started()) if interrupt else None

        def interrupted(stream):
            if talking is not None and talking.done():
                stream.clear()  # barge-in: drop what was not said yet
                return True
            return False

        stream = None
        try:
            self.transcript.append(("local", text))
            async for frame in tts.synthesize(text):
                stream = await self.stream(frame.rate)
                stream.write(frame)
                if interrupted(stream):
                    return False
            while stream is not None and stream.pending > 0:
                if self.report is not None or interrupted(stream):
                    return False
                await asyncio.sleep(0.02)
            return True
        finally:
            if talking is not None:
                talking.cancel()

    async def _speech_started(self, min_ms=300, voice_rms=400):
        voiced = 0.0
        async for frame in self.audio():
            loud = rms(frame.pcm) >= voice_rms
            voiced = voiced + frame.seconds * 1000 if loud else 0.0
            if voiced >= min_ms:
                return

    async def listen(self, timeout=10, *, stt=None, **segmenter_options):
        """The next thing the other side says, transcribed ("" if nothing
        within `timeout`)."""
        stt = stt or self.phone.stt
        if stt is None:
            raise PhoneError("listen() needs an STT: AsyncPhone(..., stt=WhisperSTT())")
        try:
            async with asyncio.timeout(timeout):
                async for utterance in utterances(self, stt, **segmenter_options):
                    self.transcript.append(("remote", utterance.text))
                    return utterance.text
        except TimeoutError:
            pass
        return ""

    async def gather(self, length=None, *, timeout=5, finish_on="#"):
        """DTMF digits received from now on: until `length` digits, the
        `finish_on` key (not included) or `timeout` seconds in total."""
        digits = ""
        try:
            async with asyncio.timeout(timeout):
                async for event in self.events(self.Dtmf):
                    if finish_on and event.digit == finish_on:
                        break
                    digits += event.digit
                    if length and len(digits) >= length:
                        break
        except TimeoutError:
            pass
        return digits

    async def request(
        self, method, body="", *, headers=None, content_type="", timeout=None
    ):
        """In-dialog request (INFO, MESSAGE...). Returns its final
        Call.Transaction (method, code, reason)."""
        lines = tuple(f"{k}: {v}" for k, v in (headers or {}).items())
        method = method.upper()
        return await self._then(
            Native.send_request,
            (method, lines, body, content_type),
            self.Transaction,
            lambda e: e.method == method and e.code >= 200,
            timeout,
        )

    async def message(self, text, content_type="text/plain"):
        """MESSAGE inside the call."""
        return await self.request("MESSAGE", text, content_type=content_type)

    async def update(self):
        """UPDATE: refresh the session without a re-INVITE."""
        await self._do(Native.refresh)

    # -- waiting --

    async def _then(self, action, args, event_type, predicate, timeout):
        """Run `action`, then wait for the first matching event after it."""
        index = len(self.timeline)
        await self._do(action, *args)
        self._cursors[event_type] = max(self._cursors.get(event_type, 0), index)
        return await self.wait_for(
            event_type, predicate, timeout=timeout or self.phone.timeouts.request
        )

    async def wait_for(
        self, event_type, predicate=None, *, timeout=10, fail_on_end=True
    ):
        """The next `event_type` event (after the previous match of that type)
        for which predicate(event) is true. Raises CallFailed if the call
        ends first, WaitTimeout on timeout.

            await call.wait_for(Call.Sip, lambda e: e.message.code == 183)
        """

        async def scan():
            index = self._cursors.get(event_type, 0)
            while True:
                while index < len(self.timeline):
                    event = self.timeline[index]
                    index += 1
                    if isinstance(event, event_type) and (
                        predicate is None or predicate(event)
                    ):
                        self._cursors[event_type] = index
                        return event
                    if (
                        fail_on_end
                        and isinstance(event, self.StateChanged)
                        and event.state == "DISCONNECTED"
                    ):
                        raise CallFailed(event.code, event.reason, event_type.__name__)
                self._changed.clear()
                await self._changed.wait()

        try:
            return await asyncio.wait_for(scan(), timeout)
        except TimeoutError:
            raise WaitTimeout(event_type.__name__, timeout, self.state) from None

    async def answered(self, timeout=None):
        """Wait for 200 OK + ACK. Raises CallFailed with the SIP code."""
        await self.wait_for(self.Answered, timeout=timeout or self.phone.timeouts.setup)

    async def ended(self, timeout=None) -> Report:
        """Wait until the call is over, however it ends."""
        if self.report is None:
            await self.wait_for(self.Ended, timeout=timeout, fail_on_end=False)
        assert self.report is not None
        return self.report

    async def amd(self, timeout=10, settle=0.0):
        """Who answered (Amd: human, machine, voicemail, sit...). With
        `settle`, keep listening that long for a beep or SIT that would
        change the result."""
        event = await self.wait_for(self.Amd, timeout=timeout)
        deadline = asyncio.get_running_loop().time() + settle
        while (left := deadline - asyncio.get_running_loop().time()) > 0:
            try:
                event = await self.wait_for(self.Amd, timeout=left)
            except PhoneError:
                break
        return event.amd

    # -- live streams --

    async def events(self, *types):
        """New events of this call (of `types`, or all) until it ends."""
        index = len(self.timeline)
        while True:
            while index < len(self.timeline):
                event = self.timeline[index]
                index += 1
                if not types or isinstance(event, types):
                    yield event
                if isinstance(event, self.Ended):
                    return
            self._changed.clear()
            await self._changed.wait()

    async def stats(self):
        """Live RTP statistics, every stats_interval, until the call ends."""
        async for event in self.events(self.Stats):
            yield event.stats

    async def audio(self):
        """Received audio while the call lasts: 20 ms AudioFrames (16-bit
        little-endian mono PCM at AUDIO_RATE). Ends when the call ends."""
        if self.state == "DISCONNECTED":
            return
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def consumer(pcm):  # PJMEDIA thread
            try:
                loop.call_soon_threadsafe(queue.put_nowait, pcm)
            except RuntimeError:
                pass  # the loop is closed

        self._audio_queues.add(queue)
        token = await self._do(Native.add_tap, consumer)
        try:
            while (pcm := await queue.get()) is not None:
                yield AudioFrame(pcm, self.AUDIO_RATE)
        finally:
            self._audio_queues.discard(queue)
            if self.state != "DISCONNECTED":
                try:
                    await self._do(Native.remove_tap, token, live=False)
                except PhoneError:
                    pass
