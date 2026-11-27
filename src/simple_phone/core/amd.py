"""Is the far end a person, an IVR/voicemail, or a network announcement?

Three layers, all on the audio this side receives (16-bit mono PCM frames):

1. SIP hints: answered within a second with no ringing points to a machine.
2. Voice pattern after the answer, like Asterisk AMD(): a person says a
   short "hello?" and waits; an IVR or voicemail talks for longer.
3. Tones (Goertzel): SIT tones mean a network announcement ("number
   not in service"); a single pure beep after the answer means voicemail.
   Speech in early media followed by a failure (4xx-6xx) without an answer
   is a network announcement too, SIT tones or not.

words_verdict() reads a transcript (optional, see Call.amd(transcribe=...)):
"leave a message" is voicemail, "not in service" a network announcement,
"press 1" an IVR.

Results: human, machine (IVR or voicemail greeting), voicemail (beep heard),
sit, silence (nobody spoke), unsure. A later tone can upgrade the result:
machine becomes voicemail on the beep, anything becomes sit. "silence" is
provisional: if someone speaks later, the voice pattern starts over from
that first voice and its result follows.

Pure Python and no pjsua2, so it can be tested with synthetic audio.
"""

import array
import math
import re
import sys
import unicodedata

RESULTS = ("human", "machine", "voicemail", "sit", "silence", "unsure", "ivr")
ANNOUNCEMENT_MS = 1000  # speech in early media before a failure: an announcement
# A voicemail beep sounds once. The same tone again within this time is a
# call-progress cadence (busy: 425 Hz, 250 ms on, 250 ms off), not a beep.
BEEP_ALONE_MS = 1000
# Detector limits that Settings exposes as amd_<name>; defaults from Asterisk.
LIMITS = (
    "initial_silence_ms",
    "greeting_ms",
    "after_greeting_silence_ms",
    "total_ms",
    "voice_rms",
    "max_words",
)
SIT_TONES = (913.8, 985.2, 1370.6, 1428.5, 1776.7)  # ITU-T E.180 segments


def sit_group(freq):
    """0 low, 1 mid, 2 high band of the SIT pattern; None if not a SIT tone."""
    nearest = min(SIT_TONES, key=lambda t: abs(t - freq))
    if abs(nearest - freq) > 30:
        return None
    return 0 if nearest < 1100 else 1 if nearest < 1600 else 2


def goertzel_ratio(samples, freq, rate, energy):
    """Share of the frame's energy at `freq`: ~1.0 for a pure tone there."""
    coeff = 2 * math.cos(2 * math.pi * freq / rate)
    s1 = s2 = 0.0
    for x in samples:
        s1, s2 = x + coeff * s1 - s2, s1
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    return 2 * power / (len(samples) * energy)


class Detector:
    def __init__(
        self,
        rate=8000,
        voice_rms=400,  # about -38 dBFS: below it a frame is silence
        initial_silence_ms=2500,
        greeting_ms=2000,
        after_greeting_silence_ms=800,
        total_ms=5000,
        min_word_ms=100,
        between_words_ms=50,
        max_words=6,
        fast_answer_s=1.0,
        listen_s=30,  # keep looking for tones this long after the answer
    ):
        self.rate = rate
        self.voice_rms = voice_rms
        self.voice_energy = voice_rms * voice_rms
        self.initial_silence_ms = initial_silence_ms
        self.greeting_ms = greeting_ms
        self.after_greeting_silence_ms = after_greeting_silence_ms
        self.total_ms = total_ms
        self.min_word_ms = min_word_ms
        self.between_words_ms = between_words_ms
        self.max_words = max_words
        self.fast_answer_s = fast_answer_s
        self.listen_ms = listen_s * 1000
        self.hints = None  # set by answered(); voice analysis starts then
        self.result = None  # latest decision, replaced as a whole
        self.version = 0  # bumped on every new decision
        self.done = False
        self.elapsed = 0  # ms of audio since the answer
        self.words = self.voice_ms = self.voice_run = self.silence_run = 0
        self.in_word = False
        self.voice_decided = False
        self.voice_result = None  # the voice layer's own latest decision
        self.voice_start = 0  # ms after the answer where voice analysis starts
        self.first_voice_ms = None  # ms of silence before the first voice
        self.tone = None  # [freq, start_ms, length_ms] of the current tone
        self.segments = []  # finished tones: (freq, start_ms, length_ms)
        self.clock = 0  # ms of audio since the first frame (tones may be early media)
        self.answer_clock = None
        self.early_sound_ms = 0  # audio above voice_rms before the answer
        self.early_tone_ms = 0  # of which pure tones (ringback, SIT)
        self.beep = None  # (freq, length, end) of a beep not yet known to be alone

    def configure(self, **limits):
        """New limits (names from LIMITS) for the decisions still to come."""
        for name, value in limits.items():
            setattr(self, name, value)
        self.voice_energy = self.voice_rms * self.voice_rms

    # -- input --

    def answered(self, answer_seconds, ringing, early_media):
        self.hints = {
            "answer_seconds": round(answer_seconds, 3),
            "ringing": ringing,
            "early_media": early_media,
            "fast_answer": answer_seconds < self.fast_answer_s and not ringing,
        }
        self.answer_clock = self.clock

    def feed(self, pcm):
        """One frame of little-endian 16-bit mono PCM. Media thread."""
        if self.done:
            return
        samples = array.array("h", pcm)
        if sys.byteorder == "big":
            samples.byteswap()
        n = len(samples)
        if not n:
            return
        frame_ms = 1000 * n / self.rate
        energy = sum(x * x for x in samples) / n
        self.clock += frame_ms
        self._tones(samples, energy, frame_ms)
        self._settle_beep()
        if self.hints is None:  # before the answer: tones, and sound for unanswered()
            if energy >= self.voice_energy:
                self.early_sound_ms += frame_ms
            return
        self.elapsed += frame_ms
        self._watch_voice(energy >= self.voice_energy, frame_ms)
        if self.elapsed >= self.listen_ms:
            self._close_tone()
            self._settle_beep(final=True)
            self.done = True

    # -- layer 2: voice pattern --

    def _watch_voice(self, voiced, frame_ms):
        began = self.elapsed - frame_ms  # where this frame starts
        if voiced and self.first_voice_ms is None:
            self.first_voice_ms = began
        if voiced and self.voice_decided and self.voice_result == "silence":
            self._start_voice_over(began)  # "silence" was provisional
        if not self.voice_decided:
            self._voice(voiced, frame_ms)

    def _start_voice_over(self, start):
        """Someone speaks after "silence": judge the voice pattern again,
        with the same limits, counted from this first voice."""
        self.words = self.voice_ms = self.voice_run = self.silence_run = 0
        self.in_word = False
        self.voice_decided = False
        self.voice_start = start

    def _voice(self, voiced, frame_ms):
        verdict = self._heard(frame_ms) if voiced else self._quiet(frame_ms)
        if verdict is None and self.elapsed - self.voice_start >= self.total_ms:
            verdict = (
                ("machine", "unsure, but answered at once")
                if (self.hints or {}).get("fast_answer")
                else ("unsure", f"no decision in {self.total_ms}ms")
            )
        if verdict is not None:
            self._decide_voice(*verdict)

    def _heard(self, frame_ms):
        """A voiced frame: count words and greeting length."""
        self.silence_run = 0
        self.voice_run += frame_ms
        if self.voice_run >= self.min_word_ms and not self.in_word:
            self.in_word = True
            self.words += 1
            if self.words == 1:
                self.voice_ms = self.voice_run
        elif self.words:
            self.voice_ms += frame_ms
        if self.words >= self.max_words:
            return "machine", f"{self.words} words"
        if self.voice_ms >= self.greeting_ms:
            return "machine", f"greeting longer than {self.greeting_ms}ms"
        return None

    def _quiet(self, frame_ms):
        """A silent frame: end the word, or decide on how long it stays quiet."""
        self.silence_run += frame_ms
        if self.silence_run >= self.between_words_ms:
            self.in_word, self.voice_run = False, 0
        quiet_for = self.elapsed - self.voice_start
        if not self.words and quiet_for >= self.initial_silence_ms:
            return "silence", "nobody spoke"
        if self.words and self.silence_run >= self.after_greeting_silence_ms:
            return "human", "short greeting, then waited"
        return None

    def _decide_voice(self, result, reason):
        self.voice_decided = True
        self.voice_result = result
        if self.voice_start:
            reason += f" after {self.voice_start / 1000:.1f} s of silence"
        current = (self.result or {}).get("result")
        if current not in ("sit", "voicemail"):  # a tone already said more
            self._publish(result, reason)

    # -- layer 3: tones --

    def unanswered(self, code, reason):
        """The call failed before the answer. Speech in early media first
        means a network announcement played the error."""
        self._close_tone()
        spoken = self.early_sound_ms - self.early_tone_ms  # ringback is no speech
        if code < 400 or spoken < ANNOUNCEMENT_MS:
            return
        if (self.result or {}).get("result") != "sit":
            seconds = spoken / 1000
            self._publish(
                "sit", f"{seconds:.1f} s of early media, then {code} {reason}"
            )

    def _tones(self, samples, energy, frame_ms):
        freq = None
        if energy >= self.voice_energy:
            crossings = sum(
                (a < 0) != (b < 0) for a, b in zip(samples, samples[1:], strict=False)
            )
            guess = crossings * self.rate / (2 * len(samples))
            if 300 <= guess <= 3000:
                best = max(
                    (goertzel_ratio(samples, f, self.rate, energy), f)
                    for f in (guess - 25, guess, guess + 25)
                )
                if best[0] >= 0.6:
                    freq = best[1]
        tone = self.tone
        if tone and freq and abs(freq - tone[0]) <= 40:
            tone[0] = (tone[0] * tone[2] + freq * frame_ms) / (tone[2] + frame_ms)
            tone[2] += frame_ms
            return
        self._close_tone()
        if freq:
            self.tone = [freq, self.clock - frame_ms, frame_ms]

    def _close_tone(self):
        if not self.tone:
            return
        freq, start, length = self.tone
        self.tone = None
        if length < 150:
            return
        if self.answer_clock is None:
            self.early_tone_ms += length
        self.segments = [s for s in self.segments if start - s[1] < 2000]
        self.segments.append((freq, start, length))
        # SIT: 274-380 ms tones from at least two of the low/mid/high bands.
        groups = {sit_group(f) for f, _, ms in self.segments if 200 <= ms <= 450} - {
            None
        }
        if len(groups) >= 2:
            tones = sorted(round(f) for f, _, _ in self.segments)
            self._publish("sit", f"SIT tones {tones} Hz")
            self.done = True
            return
        maybe_sit = sit_group(freq) is not None and length <= 450
        answered = self.answer_clock is not None and start >= self.answer_clock
        if answered and not maybe_sit and 200 <= length <= 2000:
            same = self.beep is not None and abs(self.beep[0] - freq) <= 40
            self.beep = None if same else (freq, length, self.clock)  # cadence: no beep

    def _settle_beep(self, final=False):
        """Publish a beep once it proved to be alone (not a busy cadence)."""
        if self.beep is None:
            return
        freq, length, end = self.beep
        if self.tone is not None and abs(self.tone[0] - freq) <= 40:
            self.beep = None  # the same tone again: a call-progress cadence
            return
        if final or self.clock - end >= BEEP_ALONE_MS:
            self.beep = None
            if (self.result or {}).get("result") != "sit":
                self._publish("voicemail", f"beep {round(freq)} Hz, {round(length)}ms")

    def _publish(self, result, reason):
        if (self.result or {}).get("result") == result:
            return
        self.result = {
            "result": result,
            "reason": reason,
            "after_ms": round(self.elapsed),
            "words": self.words,
            "voice_ms": round(self.voice_ms),
            "leading_silence_ms": round(
                self.elapsed if self.first_voice_ms is None else self.first_voice_ms
            ),
            "hints": self.hints,
        }
        self.version += 1


# -- optional layer 4: what the far end says (needs an STT) --

# First match wins: a greeting that says "not available, leave a message" is
# voicemail, not an announcement. Lower case, without accents.
PHRASES = (
    (
        "voicemail",
        (
            "caixa postal", "deixe sua mensagem", "deixe seu recado", "deixe o seu recado",
            "apos o sinal", "depois do sinal", "voicemail", "voice mail",
            "leave a message", "leave your message", "after the tone", "after the beep",
        ),
    ),
    (
        "sit",
        (
            "nao existe", "inexistente", "nao esta disponivel", "fora da area",
            "fora de area", "esta desligado", "nao foi possivel completar",
            "nao pode ser completada", "not in service", "no longer in service",
            "cannot be completed", "has been disconnected", "check the number",
        ),
    ),
    (
        "ivr",
        (
            "digite", "disque", "tecle", "pressione", "opcao", "menu",
            "press", "dial", "option",
        ),
    ),
)  # fmt: skip


def by_words(result, text):
    """A decision (result dict) corrected by a transcript, or None when the
    words change nothing. A beep, SIT tones or an announcement say more."""
    verdict = words_verdict(text)
    if verdict is None or result.get("result") in ("sit", "voicemail"):
        return None
    new, phrase = verdict
    reason = f'"{phrase}" in the transcript'
    return {**result, "result": new, "reason": reason, "transcript": text}


def words_verdict(text):
    """(result, phrase) for the first known phrase in a transcript, else None."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    for result, phrases in PHRASES:
        for phrase in phrases:
            if re.search(
                rf"\b{re.escape(phrase)}\b", plain
            ):  # "press", not "impressao"
                return result, phrase
    return None
