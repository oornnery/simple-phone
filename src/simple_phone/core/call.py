"""One call: state timeline, audio wiring and RTP statistics."""

import gc
import threading
import time
from dataclasses import replace
from itertools import count
from uuid import uuid4

from .._native import pjsua2 as pj
from ..events import CallEvents as C
from ..models import Amd
from .amd import LIMITS, Detector
from .config import DTMF_DIGITS
from .metrics import direction, estimate_mos, millis, utc_now

TAP_RATE = 8000  # received audio handed to Python: 16-bit mono, 20 ms frames
_tokens = count(1)
MEDIA_STATUS = {0: "NONE", 1: "ACTIVE", 2: "LOCAL_HOLD", 3: "REMOTE_HOLD", 4: "ERROR"}


class TapPort(pj.AudioMediaPort):
    """Conference port that hands received audio to Python consumers
    (the AMD detector, Call.add_tap callbacks)."""

    def __init__(self):
        super().__init__()
        self.consumers = []  # replaced as a whole, read on the media thread
        fmt = pj.MediaFormatAudio()
        fmt.init(pj.PJMEDIA_FORMAT_PCM, TAP_RATE, 1, 20000, 16)
        self.createPort("tap", fmt)

    def onFrameReceived(self, frame):
        # Runs on a PJMEDIA thread: no pjsua2 calls, and never raise into C++.
        try:
            if frame.type == pj.PJMEDIA_FRAME_TYPE_AUDIO:
                pcm = bytes(frame.buf)
                for consumer in self.consumers:
                    consumer(pcm)
        except Exception:  # noqa: BLE001, S110 - must not raise into C++
            pass


def destroy_native(port):
    """Delete a Python-backed native object (a conference port, a Buddy)
    while its Python object lives. A Buddy left to Account.shutdown() would
    be deleted twice: once there, once by the proxy.

    The bridge may still be inside put/get_frame (holding the port's grp_lock,
    waiting for the GIL) when the port goes away. If the native delete runs
    from the proxy's dealloc, that callback then lands on a dead Python object
    and segfaults. Deleting it explicitly first makes ~AudioMediaPort wait for
    the callback (GIL released) while self is still valid; disowned after.
    """
    if port is not None and port.thisown:
        port.__swig_destroy__(port)


class StreamBuffer:
    """Audio waiting to be sent: written by Python (any thread), read by the
    media thread. Handed to the API instead of the port itself, so the native
    port is never destroyed outside the engine thread."""

    def __init__(self, rate):
        self.rate = rate
        self.frame_bytes = rate // 50 * 2  # 20 ms of 16-bit mono
        self.data = bytearray()
        self.lock = threading.Lock()

    def write(self, pcm):
        with self.lock:
            self.data += pcm

    def clear(self):  # drop what was not played yet (barge-in)
        with self.lock:
            self.data.clear()

    def pending(self):
        """Seconds of audio still to play."""
        with self.lock:
            return len(self.data) / 2 / self.rate

    def take(self):
        with self.lock:
            chunk = bytes(self.data[: self.frame_bytes])
            del self.data[: self.frame_bytes]
        return chunk.ljust(self.frame_bytes, b"\0")


class StreamPort(pj.AudioMediaPort):
    """Conference port that sends what Python writes to its StreamBuffer;
    silence when the buffer is empty."""

    def __init__(self, rate=8000):
        super().__init__()
        self.buffer = StreamBuffer(rate)
        fmt = pj.MediaFormatAudio()
        fmt.init(pj.PJMEDIA_FORMAT_PCM, rate, 1, 20000, 16)
        self.createPort("stream", fmt)

    def onFrameReceived(self, frame):
        # The bridge also hands silence to ports that only transmit. Without
        # this override the SWIG base method raises inside the media thread.
        pass

    def onFrameRequested(self, frame):
        # Runs on a PJMEDIA thread: no pjsua2 calls, and never raise into C++.
        try:
            chunk = self.buffer.take()
            frame.type = pj.PJMEDIA_FRAME_TYPE_AUDIO
            frame.buf = pj.ByteVector(chunk)
            frame.size = len(chunk)
        except Exception:  # noqa: BLE001, S110 - must not raise into C++
            pass


def add_headers(tx_option, lines):
    """'Name: value' lines into a SipTxOption."""
    for line in lines:
        name, sep, value = line.partition(":")
        if not sep or not name.strip() or "\n" in line or "\r" in line:
            raise ValueError("Header must be 'Name: value' without newlines")
        header = pj.SipHeader()
        header.hName, header.hValue = name.strip(), value.strip()
        tx_option.headers.append(header)


def call_op(code=0, defaults=False):
    params = pj.CallOpParam(defaults)
    params.statusCode = code
    return params


class Call(pj.Call):
    def __init__(self, account, endpoint, call_id=pj.PJSUA_INVALID_ID, ref=None):
        super().__init__(account, call_id)
        self.endpoint = endpoint
        self.config = replace(account.config)
        self.ref = ref or uuid4().hex[:12]
        self.account_id = account.account_id
        self.pending = call_id != pj.PJSUA_INVALID_ID
        self.state = "INCOMING" if self.pending else "CALLING"
        self.held = False
        self.muted = False
        self.microphone_gain = self.speaker_gain = 1.0
        self.started = time.monotonic()
        self.answered_at = self.ended_at = self.error = None
        self.last = {}  # Call-ID, URIs, last SIP code and reason
        self.events = []
        self.dtmf = []
        self.streams = {}  # "index:generation" -> latest snapshot
        self.generation = {}
        self.links = []  # bridge connections, also keeps them alive
        self.port = self.player = self.recorder = self.sink = None
        self.tx = []  # links of the current source (echo, mic, wav)
        self.speaker = None  # link to the playback device, when listening
        self.streams_out = []  # StreamPorts connected to this call (say)
        self.tones = None  # ToneGenerator for in-band DTMF
        # Outgoing calls only: is the far end a person, an IVR, an announcement?
        limits = {name: getattr(self.config, f"amd_{name}") for name in LIMITS}
        wanted = self.config.amd and not self.pending
        self.amd = Detector(TAP_RATE, **limits) if wanted else None
        self.taps = {}  # token -> callable(pcm bytes), called on the media thread
        self.plays = {}  # token -> AudioMediaPlayer sending a WAV into the call
        self.tap_port = None
        self.amd_seen = 0
        self.early_media = False  # audio flowed before the answer (183)

    def media_op(self, code=0):
        """CallOpParam offering this call's streams: audio, plus RTT text
        when Settings.text (PJSUA would offer text on every call)."""
        params = call_op(code, defaults=True)
        params.opt.audioCount, params.opt.videoCount = 1, 0
        params.opt.textCount = int(self.config.text)
        return params

    # -- PJSUA2 callbacks (always on the thread that runs libHandleEvents) --

    def identity(self, call_id=None):
        return {
            "account_id": self.account_id,
            "ref": self.ref,
            "call_id": call_id or self.last.get("call_id"),
        }

    def emit(self, kind, **fields):
        """A typed event of this call; kind is a CallEvents class."""
        self.endpoint.emit(kind, **{**self.identity(), **fields})

    def onCallState(self, prm):
        info = self.getInfo()
        code = int(info.lastStatusCode)
        self.state = info.stateText
        self.last = {
            "call_id": info.callIdString,
            "local_uri": info.localUri,
            "remote_uri": info.remoteUri,
            "last_sip_code": code,
            "last_sip_reason": info.lastReason,
        }
        self.events.append(
            {
                "seconds": round(time.monotonic() - self.started, 3),
                "state": info.stateText,
                "sip_code": code,
                "reason": info.lastReason,
            }
        )
        if info.state == pj.PJSIP_INV_STATE_DISCONNECTED and not self.answered_at:
            self.amd_unanswered(code, info.lastReason)  # before StateChanged
        self.emit(
            C.StateChanged,
            state=info.stateText,
            code=code,
            reason=info.lastReason,
            call_id=info.callIdString,
            remote_uri=info.remoteUri,
        )
        if info.state == pj.PJSIP_INV_STATE_CONFIRMED and not self.answered_at:
            self.answered_at = time.monotonic()
            if self.amd is not None:
                self.amd.answered(
                    self.answered_at - self.started,
                    ringing=any(e["state"] == "EARLY" for e in self.events),
                    early_media=self.early_media,
                )
        elif info.state == pj.PJSIP_INV_STATE_DISCONNECTED:
            self.ended_at = time.monotonic()
            # Drop this object now, while the PJSUA slot is still ours.
            self.endpoint.finish(self)

    def onCallMediaState(self, prm):
        try:
            # info.media is a view into CallInfo: keep `info` alive while
            # iterating, or the entries point to freed memory.
            info = self.getInfo()
            self.held = any(
                m.status == pj.PJSUA_CALL_MEDIA_LOCAL_HOLD for m in info.media
            )
            for media in info.media:
                self.emit(
                    C.MediaChanged,
                    held=self.held,
                    status=MEDIA_STATUS.get(media.status, str(media.status)),
                )
                if (
                    media.type == pj.PJMEDIA_TYPE_AUDIO
                    and media.status == pj.PJSUA_CALL_MEDIA_ACTIVE
                ):
                    audio = self.getAudioMedia(media.index)
                    if audio.getPortId() != self.port:  # new or re-created
                        self.port = audio.getPortId()
                        self.wire(audio)
            self.sample("media_state")
        except pj.Error as exc:
            self.error = exc.info()

    def onStreamCreated(self, prm):
        # A re-INVITE can replace the stream at the same index. Generations
        # keep the counters of the old stream from being overwritten.
        index = int(prm.streamIdx)
        self.generation[index] = self.generation.get(index, 0) + 1

    def onStreamDestroyed(self, prm):
        # Last chance to read the counters, e.g. when the peer hangs up.
        self.sample_stream(int(prm.streamIdx), "stream_destroyed")

    def onDtmfDigit(self, prm):
        self.dtmf.append({"at": utc_now(), "digit": prm.digit})
        self.emit(
            C.Dtmf,
            digit=prm.digit,
            method="info" if prm.method == pj.PJSUA_DTMF_METHOD_SIP_INFO else "rfc4733",
        )

    def onCallTransferStatus(self, prm):
        self.emit(
            C.TransferStatus,
            code=prm.statusCode,
            reason=prm.reason,
            final=prm.finalNotify,
            success=200 <= prm.statusCode < 300,
        )

    def onCallTsxState(self, prm):
        # Do not retain native callback views beyond this callback.
        try:
            event = prm.e
            body = event.body
            state = body.tsxState
            tsx = state.tsx
            self.emit(
                C.Transaction,
                method=tsx.method,
                code=tsx.statusCode,
                reason=tsx.statusText,
            )
        except AttributeError, pj.Error:
            pass

    def onInstantMessage(self, prm):
        self.emit(
            C.Message,
            from_uri=prm.fromUri,
            content_type=prm.contentType,
            body=prm.msgBody,
        )

    def onCallRedirected(self, prm):
        # 3xx: follow only when asked to, like follow_redirects in httpx.
        follow = self.config.follow_redirects
        self.emit(C.Redirected, target=prm.targetUri, followed=follow)
        return pj.PJSIP_REDIRECT_ACCEPT if follow else pj.PJSIP_REDIRECT_STOP

    def onCallTransferRequest(self, prm):
        accepted = self.config.accept_transfers
        if accepted:
            prm.newCall = self.endpoint.child_call(self)
            prm.opt.textCount = int(self.config.text)
        else:
            prm.statusCode = 603
        self.emit(C.TransferRequest, target=prm.dstUri, accepted=accepted)

    def onCallReplaceRequest(self, prm):
        prm.newCall = self.endpoint.child_call(self)
        prm.opt.textCount = int(self.config.text)

    def onCallRxText(self, prm):
        self.emit(C.Text, text=prm.text)

    def onCallRxReinvite(self, prm):
        self.emit(C.Reinvite, has_offer=prm.offer is not None)

    # -- audio --

    def connect(self, source, sink):
        source.startTransmit(sink)
        link = (source, sink)
        self.links.append(link)
        return link

    def wire(self, audio):
        config = self.config
        self.early_media = self.early_media or self.state == "EARLY"
        # The call must stay connected to something: PJSIP closes an idle
        # sound device after 1 s, and the media clock (and all RTP) with it.
        if self.sink is None:
            self.sink = pj.AudioMediaPort()  # plain C++ port, no Python callback
            fmt = pj.MediaFormatAudio()
            fmt.init(pj.PJMEDIA_FORMAT_PCM, 8000, 1, 20000, 16)
            self.sink.createPort("sink", fmt)
        self.connect(audio, self.sink)
        self.connect_source(audio)
        if config.speaker:
            self.speaker = self.connect(audio, self.devices().getPlaybackDevMedia())
        if config.record:
            if self.recorder is None:
                self.recorder = pj.AudioMediaRecorder()
                self.recorder.createRecorder(str(config.record))
            self.connect(audio, self.recorder)
        for stream in self.streams_out:
            self.connect(stream, audio)
        if self.tones is not None:
            self.connect(self.tones, audio)
        self.retap(audio)
        self.apply_gain()

    def audio(self):
        """The call's port in the conference bridge; the call must be live."""
        return self.getAudioMedia(-1)

    @staticmethod
    def devices():
        return pj.Endpoint.instance().audDevManager()

    def connect_source(self, audio):
        """What this call transmits: silent (nothing), echo, mic or wav."""
        config = self.config
        if config.media == "echo":  # received audio goes back out
            self.tx.append(self.connect(audio, audio))
        elif config.media == "mic":
            self.tx.append(self.connect(self.devices().getCaptureDevMedia(), audio))
        elif config.media == "wav":
            if self.player is None:
                self.player = pj.AudioMediaPlayer()
                options = 0 if config.wav_loop else pj.PJMEDIA_FILE_NO_LOOP
                self.player.createPlayer(str(config.wav), options)
            self.tx.append(self.connect(self.player, audio))

    def unlink(self, links):
        for source, sink in links:
            if not self.ended_at:
                try:
                    source.stopTransmit(sink)
                except pj.Error:
                    pass
        gone = {id(link) for link in links}
        self.links = [link for link in self.links if id(link) not in gone]

    def set_source(self, media, wav=None, loop=False):
        """Change what the call transmits while it runs."""
        audio = self.audio()
        self.unlink(self.tx)
        self.tx, self.player = [], None
        self.config = replace(
            self.config, media=media, wav=wav or self.config.wav, wav_loop=loop
        )
        if media == "mic":
            self.endpoint.setup_audio(self.config)  # the sound card may be needed now
        self.connect_source(audio)

    def set_speaker(self, enabled):
        """Play the received audio on the speaker (or stop)."""
        audio = self.audio()
        self.config = replace(self.config, speaker=enabled)
        if self.speaker is not None:
            self.unlink([self.speaker])
            self.speaker = None
        if enabled:
            self.endpoint.setup_audio(self.config)
            self.speaker = self.connect(audio, self.devices().getPlaybackDevMedia())

    def open_stream(self, rate=8000):
        """A StreamPort connected to this call; returns its StreamBuffer."""
        stream = StreamPort(rate)
        self.streams_out.append(stream)
        self.connect(stream, self.audio())
        return stream.buffer  # the port itself stays on this thread

    def play_digits(self, digits, on_ms=100, off_ms=100):
        """In-band DTMF: the tones themselves, inside the audio."""
        audio = self.audio()
        if self.tones is None:
            self.tones = pj.ToneGenerator()
            self.tones.createToneGenerator(8000, 1)
            self.connect(self.tones, audio)
        sequence = pj.ToneDigitVector()
        for digit in digits:
            tone = pj.ToneDigit()
            tone.digit, tone.on_msec, tone.off_msec, tone.volume = (
                digit,
                on_ms,
                off_ms,
                0,
            )
            sequence.append(tone)
        self.tones.playDigits(sequence)

    def rewire(self):
        """Apply a media change to audio already flowing (e.g. since a 183)."""
        if self.port is None or self.ended_at:
            return
        self.unlink(self.links[::-1])
        self.tx, self.speaker = [], None
        self.player = None  # a new WAV, or none, starts from the beginning
        self.wire(self.getAudioMedia(-1))

    def apply_gain(self):
        if self.port is None or self.ended_at:
            return
        audio = self.getAudioMedia(-1)
        # Rx: bridge -> call (microphone); Tx: call -> bridge (speaker).
        audio.adjustRxLevel(0 if self.muted else self.microphone_gain)
        audio.adjustTxLevel(self.speaker_gain)

    def set_recording(self, path):
        if self.port is None:
            raise RuntimeError("No active audio stream")
        audio = self.getAudioMedia(-1)
        if self.recorder is not None:
            self.unlink([link for link in self.links if link[1] is self.recorder])
            self.recorder = None
        if path:
            self.recorder = pj.AudioMediaRecorder()
            self.recorder.createRecorder(str(path))
            self.connect(audio, self.recorder)
        path = str(path) if path else None
        self.config = replace(self.config, record=path)

    def set_amd_limits(self, limits):
        """amd_* limits for this call only; Settings validates them."""
        self.config = replace(self.config, **limits)
        if self.amd is not None:
            self.amd.configure(
                **{name: getattr(self.config, f"amd_{name}") for name in LIMITS}
            )

    def amd_unanswered(self, code, reason):
        """A failure before the answer may follow an announcement in early
        media: let the detector judge it, and emit what it says now."""
        if self.amd is not None:
            self.amd.unanswered(code, reason)
            self.emit_amd()  # no retap(): the media is going away

    def poll_amd(self):
        """Emit new AMD decisions; detach the port once it is done.

        Called from the thread that runs libHandleEvents().
        """
        if self.amd is None:
            return
        self.emit_amd()
        if self.amd.done and self.tap_port is not None:
            self.retap()

    def emit_amd(self):
        """A Call.Amd event for a decision not emitted yet."""
        if self.amd is None or self.amd.version == self.amd_seen:
            return
        self.amd_seen = self.amd.version
        if self.amd.result is not None:
            self.emit(C.Amd, amd=Amd.parse(self.amd.result))

    # -- extra audio into the call (e.g. text-to-speech) --

    def play(self, path):
        """Send a WAV once, mixed with the call's media. Returns a token."""
        player = pj.AudioMediaPlayer()
        player.createPlayer(str(path), pj.PJMEDIA_FILE_NO_LOOP)
        self.connect(player, self.audio())
        token = next(_tokens)
        self.plays[token] = player
        return token

    def stop_play(self, token):
        player = self.plays.pop(token, None)
        if player is not None:
            self.unlink([link for link in self.links if link[0] is player])

    # -- received audio to Python --

    def add_tap(self, consumer):
        """Call consumer(pcm) for every received 20 ms frame (8 kHz, 16-bit
        mono) on a media thread. Returns a token for remove_tap()."""
        token = next(_tokens)
        self.taps[token] = consumer
        self.retap()
        return token

    def remove_tap(self, token):
        self.taps.pop(token, None)
        self.retap()

    def retap(self, audio=None):
        """Connect the tap port while something consumes it; detach it after."""
        consumers = list(self.taps.values())
        if self.amd is not None and not self.amd.done:
            consumers.append(self.amd.feed)
        port = self.tap_port
        connected = port is not None and any(t is port for _, t in self.links)
        if consumers and not self.ended_at and (audio or self.port is not None):
            if port is None:
                port = self.tap_port = TapPort()
            port.consumers = consumers
            if not connected:
                self.connect(audio or self.getAudioMedia(-1), port)
        elif port is not None:
            port.consumers = []
            self.unlink([link for link in self.links if link[1] is port])
            self.tap_port = None
            destroy_native(port)

    def release_media(self):
        """Disconnect the bridge, then drop the player and recorder.

        Only while the call is alive: once it has ended PJSIP has already
        removed its port, and disconnecting a removed port logs "Remove
        port ... PJ_EINVAL" on some builds and aborts on others.
        """
        self.unlink(self.links[::-1])
        for port in [self.tap_port, *self.streams_out]:
            destroy_native(port)
        self.player = self.recorder = self.tap_port = self.sink = None
        self.tones, self.speaker, self.tx = None, None, []
        self.plays.clear()
        self.streams_out.clear()
        gc.collect()

    # -- actions: called on the engine thread --

    def accept(self, code=200):
        """Answer: 1xx keeps it ringing (183 = early media), 2xx connects."""
        if not 100 <= code <= 299:
            raise ValueError("Use accept for 1xx/2xx, reject for rejection")
        if not self.pending:
            raise RuntimeError("No incoming call")
        if code >= 200:
            self.endpoint.setup_audio(self.config)
            self.pending = False
        self.answer(self.media_op(code))

    def reject(self, code=486):
        if not 300 <= code <= 699:
            raise ValueError("Rejection must be 300..699")
        if not self.pending:
            raise RuntimeError("No incoming call")
        self.hangup(call_op(code))

    def end(self):
        self.hangup(call_op())

    def configure(self, changes):
        """Media of an incoming call, before it is answered."""
        if not self.pending:
            raise RuntimeError("Media can only change before answering")
        if set(changes) - {"media", "wav", "speaker", "record"}:
            raise ValueError("Only media, wav, speaker and record can change")
        self.config = replace(self.config, **changes)
        self.rewire()  # early media (183) may already be flowing

    def send_dtmf(self, digits, method="rfc4733"):
        if not digits or set(digits) - DTMF_DIGITS:
            raise ValueError("DTMF accepts only 0-9, *, #, A-D")
        match method:
            case "inband":
                self.play_digits(digits)
            case "rfc4733":
                self.dialDtmf(digits)
            case "info":
                params = pj.CallSendDtmfParam()
                params.method, params.digits = pj.PJSUA_DTMF_METHOD_SIP_INFO, digits
                self.sendDtmf(params)
            case _:
                raise ValueError("DTMF method must be rfc4733, info or inband")
        self.emit(C.DtmfSent, digits=digits, method=method)

    def hold(self):
        self.setHold(call_op())

    def unhold(self):
        params = self.media_op()
        params.opt.flag = pj.PJSUA_CALL_UNHOLD
        self.reinvite(params)

    def transfer(self, target):
        self.xfer(self.config.uri(target), call_op())

    def transfer_to(self, other):
        """Attended transfer: our peer goes to `other`'s peer (Replaces)."""
        if other is self:
            raise ValueError("Attended transfer needs two different calls")
        self.xferReplaces(other, call_op())

    def conference(self, other, enabled=True):
        if other is self:
            raise ValueError("Conference needs two different calls")
        a, b = self.getAudioMedia(-1), other.getAudioMedia(-1)
        if enabled:
            self.connect(a, b)
            other.connect(b, a)
            return
        # getAudioMedia() returns new objects: compare the bridge port IDs
        self.unlink(
            [link for link in self.links if link[1].getPortId() == b.getPortId()]
        )
        other.unlink(
            [link for link in other.links if link[1].getPortId() == a.getPortId()]
        )

    def mute(self, enabled=True):
        self.muted = enabled
        self.apply_gain()

    def gain(self, microphone=1.0, speaker=1.0):
        if not all(0 <= value <= 4 for value in (microphone, speaker)):
            raise ValueError("Gain must be between 0 and 4")
        self.microphone_gain, self.speaker_gain = microphone, speaker
        self.apply_gain()

    def send_request(self, method, headers=(), body="", content_type=""):
        """In-dialog request (INFO...); its response is a `transaction` event."""
        params = pj.CallSendRequestParam()
        params.method = method.upper()
        add_headers(params.txOption, headers)
        if body:
            params.txOption.contentType = content_type or "text/plain"
            params.txOption.msgBody = body
        self.sendRequest(params)

    def refresh(self):
        """UPDATE: refresh the session without a re-INVITE."""
        self.update(self.media_op())

    def send_text(self, text):
        """RTT (RFC 4103): text sent as typed, over the call's text stream."""
        if not self.config.text:
            raise RuntimeError("RTT is off: Settings(text=True)")
        params = pj.CallSendTextParam()
        params.text = text
        self.sendText(params)

    def describe(self, media=True):
        """PJSUA's text dump: dialog, SDP, media per stream."""
        return self.dump(media, "  ")

    # -- statistics --

    def sample_stream(self, index, source):
        try:
            stream_stat = self.getStreamStat(index)
            stat = stream_stat.rtcp
            info = self.getStreamInfo(index)
        except pj.Error:
            return  # the stream is already gone
        generation = self.generation.get(index, 0)
        try:
            transport = self.getMedTransportInfo(index)
            local_rtp, source_rtp = transport.localRtpName, transport.srcRtpName
        except pj.Error:
            local_rtp = source_rtp = ""
        rx, rtt = direction(stat.rxStat), millis(stat.rttUsec)
        jbuf = stream_stat.jbuf
        self.streams[f"{index}:{generation}"] = {
            "media_index": index,
            "generation": generation,
            "sampled_at": utc_now(),
            "sample_source": source,
            "codec": info.codecName,
            "clock_rate_hz": int(info.codecClockRate),
            "remote_rtp": info.remoteRtpAddress,
            "local_rtp": local_rtp,
            "source_rtp": source_rtp,
            "tx": direction(stat.txStat),
            "rx": rx,
            "rtt_ms": rtt,
            "jitter_buffer": {
                "avg_delay_ms": int(jbuf.avgDelayMsec),
                "max_delay_ms": int(jbuf.maxDelayMsec),
                "lost": int(jbuf.lost),
                "discarded": int(jbuf.discard),
            },
            "mos_estimated": estimate_mos(rx, rtt)
            if info.codecName.upper() in ("PCMA", "PCMU")
            else None,
        }

    def sample(self, source="periodic"):
        # Without a native call ID (failed makeCall), getInfo() would abort
        # the process instead of raising.
        if self.ended_at or self.getId() < 0:
            return
        try:
            info = self.getInfo()
            for media in info.media:
                if media.type == pj.PJMEDIA_TYPE_AUDIO:
                    self.sample_stream(int(media.index), source)
        except pj.Error:
            pass

    def report(self):
        first = {e["state"]: e["seconds"] for e in reversed(self.events)}
        end = self.ended_at or time.monotonic()
        return {
            "account_id": self.account_id,
            "call_ref": self.ref,
            **self.last,
            "answered": self.answered_at is not None,
            "first_early_state_seconds": first.get("EARLY"),
            "answer_time_seconds": first.get("CONFIRMED"),
            "connected_seconds": (
                round(end - self.answered_at, 3) if self.answered_at else 0
            ),
            "events": self.events,
            "dtmf_received": self.dtmf,
            "amd": self.amd.result if self.amd else None,
            "streams": list(self.streams.values()),
        }
