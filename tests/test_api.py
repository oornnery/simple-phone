import asyncio
import contextlib
import tempfile
import time
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

from simple_phone import (
    AsyncPhone,
    Call,
    CallEvent,
    CallFailed,
    Limits,
    Phone,
    PhoneError,
    PoolTimeout,
    Settings,
    Timeouts,
    WaitTimeout,
)
from simple_phone.media import noise, save_wav, silence


def local(user, account_id, rtp_port, port=5090):
    return Settings(
        server="127.0.0.1",
        user=user,
        account_id=account_id,
        register=False,
        local_port=port,
        rtp_port=rtp_port,
        log_level=0,
    )


def collect(phone, kind):
    """Every `kind` event of `phone` from now on, in a list."""
    seen = []
    phone.on(kind)(seen.append)
    return seen


async def until(condition, timeout=5):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.02)


@dataclass(kw_only=True)
class Note(CallEvent):
    """An event of the application's own, for call.emit()."""

    text: str


class ApiTest(unittest.IsolatedAsyncioTestCase):
    """Real calls between two accounts of one local endpoint."""

    async def asyncSetUp(self):
        self.phone = AsyncPhone(local("1001", "a", 46000), limits=Limits(max_calls=8))
        await self.phone.__aenter__()
        self.addAsyncCleanup(self.phone.close)
        self.other = await self.phone.account(local("1002", "b", 46200))

    async def answer_with_echo(self):
        @self.other.on(AsyncPhone.Incoming)
        async def answer(event):
            await event.call.answer(media="echo")

    async def test_audio_device_ids_are_list_positions(self):
        # No sound card in CI: then this only checks the call works.
        found = await self.phone.devices()
        self.assertEqual([d["id"] for d in found], list(range(len(found))))

    async def answer_mute_then_speak(self):
        """The far end answers with 3 s of silence, then a long greeting."""
        greeting = Path(tempfile.mkdtemp()) / "late.wav"
        save_wav(greeting, silence(3) + noise(6))

        @self.other.on(AsyncPhone.Incoming)
        async def answer(event):
            await event.call.answer(media="wav", wav=greeting)

    async def test_amd_waits_out_a_mute_answer(self):
        await self.answer_mute_then_speak()
        async with self.phone.call(self.other.uri) as call:
            amd = await call.amd(timeout=10, settle=3)
        self.assertEqual(amd.result, "machine", amd.reason)
        self.assertAlmostEqual(amd.leading_silence_ms, 3000, delta=300)
        results = [e.amd.result for e in call.timeline if isinstance(e, Call.Amd)]
        self.assertEqual(results, ["silence", "machine"])

    async def test_amd_limits_for_one_call(self):
        await self.answer_mute_then_speak()
        async with self.phone.call(self.other.uri) as call:
            amd = await call.amd(timeout=10, amd_initial_silence_ms=5000)
        self.assertEqual(amd.result, "machine", amd.reason)  # no "silence" first
        with self.assertRaises(ValueError):
            async with self.phone.call(self.other.uri) as call:
                await call.amd(amd_greeting_ms=1)

    async def test_early_media_announcement_then_404_is_sit(self):
        announcement = Path(tempfile.mkdtemp()) / "announcement.wav"
        save_wav(announcement, noise(3))

        @self.other.on(AsyncPhone.Incoming)
        async def announce(event):
            await event.call.answer(183, media="wav", wav=announcement)
            await asyncio.sleep(2)
            await event.call.reject(404)

        call = await self.phone.dial(self.other.uri)
        amd = await call.amd(timeout=10)
        self.assertEqual(amd.result, "sit", amd.reason)
        self.assertIn("404", amd.reason)

    async def test_transcript_corrects_the_sound_verdict(self):
        class Voicemail:  # stands in for WhisperSTT
            async def transcribe(self, pcm, rate):
                return "Oi, aqui é a Ana. Deixe sua mensagem após o sinal."

        greeting = Path(tempfile.mkdtemp()) / "greeting.wav"
        save_wav(greeting, noise(6))

        @self.other.on(AsyncPhone.Incoming)
        async def answer(event):
            await event.call.answer(media="wav", wav=greeting)

        async with self.phone.call(self.other.uri) as call:
            with self.assertRaises(PhoneError):  # no STT: transcribe is refused
                await call.amd(transcribe=1)
            self.phone.stt = Voicemail()
            amd = await call.amd(timeout=10, transcribe=2)
        self.assertEqual(amd.result, "voicemail", amd.reason)  # sound alone: machine
        self.assertIn("Deixe sua mensagem", amd.raw["transcript"])
        results = [e.amd.result for e in call.timeline if isinstance(e, Call.Amd)]
        self.assertEqual(results, ["machine", "voicemail"])

    async def test_account_from_keyword_fields(self):
        third = await self.phone.account(user="1003")
        self.assertEqual(third.account_id, "1003")
        self.assertEqual(third.settings.rtp_port, 46400)  # 200 above the last
        self.assertEqual(third.uri, "sip:1003@127.0.0.1:5090")

        @third.on(AsyncPhone.Incoming)
        async def answer(event):
            await event.call.answer()

        async with self.phone.call(third.uri) as call:
            self.assertEqual(call.state, "CONFIRMED")
        with self.assertRaises(ValueError):
            await self.phone.account(register=False)

    async def test_call_scope_events_and_report(self):
        await self.answer_with_echo()
        digits = []

        @self.other.on(Call.Dtmf, digit="2")
        def two(event):
            digits.append(event.digit)

        async with self.phone.call(self.other.uri, headers={"X-Test": "api"}) as call:
            self.assertEqual(call.response.code, 200)
            self.assertIn("100", [str(m.code) for m in call.history])
            await call.dtmf("42")
            stats = await call.wait_for(Call.Stats, lambda e: e.stats.rx_packets >= 20)
            self.assertEqual(stats.stats.codec, "PCMA")
            self.assertIsNotNone(stats.stats.jitter_buffer_ms)
        report = call.report
        self.assertTrue(report.answered)
        self.assertEqual(call.trace.flow()[:2], ["INVITE", "100"])
        self.assertIn("BYE", call.trace.flow())
        self.assertEqual(digits, ["2"])
        self.assertEqual(self.other.errors, [])

    async def test_rejected_call_raises_with_code(self):
        call = await self.phone.dial(self.other.uri)
        incoming = await self.other.incoming(timeout=5)
        invite = await incoming.wait_for(
            Call.Sip, lambda e: e.message.method == "INVITE"
        )
        self.assertTrue(invite.message.has_sdp)
        await incoming.reject(486)
        with self.assertRaises(CallFailed) as failure:
            await call.answered(timeout=5)
        self.assertEqual(failure.exception.code, 486)
        self.assertFalse((await call.ended(timeout=5)).answered)

    async def test_call_scope_raises_when_not_answered(self):
        @self.other.on(AsyncPhone.Incoming)
        async def busy(event):
            await event.call.reject(603)

        with self.assertRaises(CallFailed) as failure:
            async with self.phone.call(self.other.uri):
                pass
        self.assertEqual(failure.exception.code, 603)

    async def test_requests_and_messages_outside_and_inside_a_call(self):
        await self.answer_with_echo()
        received = []
        self.other.on(AsyncPhone.Message)(received.append)
        self.assertEqual((await self.phone.options(self.other.uri)).code, 200)
        self.assertEqual((await self.phone.message(self.other.uri, "café")).code, 200)
        await asyncio.sleep(0.2)
        self.assertEqual([m.body for m in received], ["café"])

        async with self.phone.call(self.other.uri) as call:
            info = await call.request(
                "INFO", "Signal=5", content_type="application/dtmf-relay"
            )
            self.assertEqual((info.method, info.code), ("INFO", 200))

    async def test_events_stream_and_invalid_target(self):
        await self.answer_with_echo()
        seen = []

        async def watch():
            async for event in self.phone.events(Call.StateChanged):
                seen.append(event.state)
                if event.state == "DISCONNECTED":
                    return

        watcher = asyncio.create_task(watch())
        async with self.phone.call(self.other.uri):
            pass
        await asyncio.wait_for(watcher, 5)
        self.assertEqual(seen[0], "CALLING")
        self.assertIn("CONFIRMED", seen)
        with self.assertRaises(ValueError):
            await self.phone.dial("sip:not a uri")

    async def test_wait_for_times_out(self):
        await self.answer_with_echo()
        async with self.phone.call(self.other.uri) as call:
            with self.assertRaises(WaitTimeout):
                await call.wait_for(Call.Dtmf, timeout=0.3)

    async def test_rtp_flows_on_every_call_after_early_media(self):
        # Regression: a silent leg left the sound device idle, PJSIP closed it
        # and later calls sent no RTP; answer(media=) after 183 was ignored.
        @self.other.on(AsyncPhone.Incoming)
        async def answer(event):
            await event.call.answer(183)
            await asyncio.sleep(0.3)
            await event.call.answer(media="echo")

        for _ in range(3):
            async with self.phone.call(self.other.uri) as call:
                event = await call.wait_for(
                    Call.Stats, lambda e: e.stats.rx_packets >= 20
                )
                self.assertGreaterEqual(event.stats.rx_packets, 20)
            await asyncio.sleep(1.5)  # longer than PJSIP's 1 s idle close

    async def test_conference_dump_duration_and_attended_transfer(self):
        await self.answer_with_echo()
        third = await self.phone.account(local("1003", "c", 46400))

        @third.on(AsyncPhone.Incoming)
        async def answer(event):
            await event.call.answer(media="echo")

        to_b = await self.phone.dial(self.other.uri)
        to_c = await self.phone.dial(third.uri)
        await to_b.answered()
        await to_c.answered()
        await asyncio.sleep(0.3)
        self.assertGreater(to_b.duration, 0.2)
        self.assertIn("PCMA", await to_b.dump())
        await to_b.conference(to_c)
        await to_b.conference(to_c, enabled=False)

        await to_b.attended_transfer(to_c)
        status = await to_b.wait_for(Call.TransferStatus, lambda e: e.final)
        self.assertTrue(status.success, status)
        await to_c.ended(5)  # b's INVITE with Replaces took c's leg
        await to_b.hangup()  # the transferor leaves after the NOTIFY 200
        self.assertEqual(to_b.duration, to_b.report.connected_seconds)

    async def test_hold_unhold_emit_and_session_options(self):
        third = await self.phone.account(
            replace(
                local("1003", "c", 46400),
                prack="mandatory",
                session_timer="always",
                mwi=True,
            )
        )

        @third.on(AsyncPhone.Incoming)
        async def answer(event):
            await event.call.answer(media="echo")

        seen = []
        self.phone.on(Note)(seen.append)
        async with self.phone.call(third.uri) as call:
            self.assertTrue((await call.hold()).held)
            self.assertFalse((await call.unhold()).held)  # right after hold()
            call.emit(Note(text="café"))
            event = await call.wait_for(Note)
        self.assertIs(event.call, call)
        self.assertEqual([e.text for e in seen], ["café"])
        self.assertIn("PRACK", call.trace.flow())  # c requires 100rel
        self.assertIn("session-expires", call.response.headers)

        # An unsolicited NOTIFY, as a PBX sends when voicemail arrives
        mwi = []
        third.on(AsyncPhone.Mwi)(mwi.append)
        await self.phone.request(
            "NOTIFY",
            third.uri,
            "Messages-Waiting: yes\r\nVoice-Message: 2/8 (0/0)\r\n",
            headers={"Event": "message-summary", "Subscription-State": "active"},
            content_type="application/simple-message-summary",
        )
        await asyncio.sleep(0.1)
        self.assertTrue(mwi[0].waiting)
        self.assertIn("Voice-Message: 2/8", mwi[0].body)

    def test_invalid_session_options(self):
        with self.assertRaises(ValueError):
            Settings(server="x", user="1", prack="yes")
        with self.assertRaises(ValueError):
            Settings(server="x", user="1", session_timer="on")

    async def test_real_time_text(self):
        c = await self.phone.account(replace(local("1003", "c", 46400), text=True))
        d = await self.phone.account(replace(local("1004", "d", 46600), text=True))
        answered = []

        @d.on(AsyncPhone.Incoming)
        async def answer(event):
            answered.append(event.call)
            await event.call.answer()

        async with c.call(d.uri) as call:
            sdp = next(m for m in call.trace if m.method == "INVITE").raw
            self.assertIn("m=text", sdp)
            await call.send_text("olx\ba")
            await until(lambda: answered[0].text_received == "ola")

    async def test_no_text_stream_by_default(self):
        await self.answer_with_echo()
        async with self.phone.call(self.other.uri) as call:
            invite = next(m for m in call.trace if m.method == "INVITE")
            self.assertNotIn("m=text", invite.raw)
            with self.assertRaises(PhoneError):
                await call.send_text("x")

    async def test_presence_typing_and_dialog_state(self):
        presence = collect(self.other, AsyncPhone.Presence)
        await self.other.subscribe(self.phone.uri)
        await until(lambda: presence and presence[-1].online is False)  # default
        await self.phone.set_presence(True)
        await until(lambda: presence[-1].online)
        await self.phone.set_presence(False, "in a meeting")
        await until(lambda: presence[-1].online is False)
        self.assertEqual(presence[-1].note, "in a meeting")
        await self.other.unsubscribe(self.phone.uri)

        typing = collect(self.other, AsyncPhone.Typing)
        await self.phone.typing(self.other.uri)
        await until(lambda: typing)
        self.assertTrue(typing[0].typing)

        # BLF: the NOTIFY a PBX sends for a watched extension
        blf = collect(self.other, AsyncPhone.DialogState)
        xml = (
            '<dialog-info entity="sip:2000@pbx" state="full" version="1">'
            '<dialog id="1"><state>early</state></dialog></dialog-info>'
        )
        with contextlib.suppress(WaitTimeout):  # PJSUA ignores it: no subscription
            await self.phone.request(
                "NOTIFY",
                self.other.uri,
                xml,
                headers={"Event": "dialog", "Subscription-State": "active"},
                content_type="application/dialog-info+xml",
                timeout=1,
            )
        await until(lambda: blf)
        self.assertEqual((blf[0].uri, blf[0].state), ("sip:2000@pbx", "early"))

    async def test_rejected_incoming_and_nat_without_stun(self):
        rejected = collect(self.other, AsyncPhone.Rejected)
        call = await self.phone.dial(self.other.uri, headers={"Require": "foo"})
        with self.assertRaises(CallFailed):
            await call.answered(timeout=5)
        await until(lambda: rejected)
        self.assertEqual(rejected[0].code, 420)
        with self.assertRaises(PhoneError):
            await self.phone.nat_type()

    async def test_ip_changed(self):
        await self.phone.ip_changed()

    async def test_dial_all_reports_each_target(self):
        await self.answer_with_echo()

        async def handle(call):
            await call.answered(timeout=2)
            return "ok"

        results = await self.phone.dial_all(
            [self.other.uri, "sip:9@127.0.0.1:5999", self.other.uri], handle
        )
        self.assertEqual([r for _, r in results][::2], ["ok", "ok"])
        self.assertIsInstance(results[1][1], WaitTimeout)


class LimitsTest(unittest.IsolatedAsyncioTestCase):
    async def test_slots_and_pacing(self):
        limits = Limits(max_calls=1, calls_per_second=5)  # one dialed call at once
        async with AsyncPhone(local("1001", "a", 46000), limits=limits) as phone:
            phone.on(AsyncPhone.Incoming)(lambda e: e.call.answer(media="echo"))
            caller = await phone.account(local("1002", "b", 46200))
            started = time.monotonic()
            first = await caller.dial(phone.uri)
            await first.answered(timeout=5)
            caller.timeouts = Timeouts(pool=0.5)
            with self.assertRaises(PoolTimeout):
                await caller.dial(phone.uri)  # both slots are busy
            await first.hangup()
            second = await caller.dial(phone.uri)  # a slot is free again
            await second.answered(timeout=5)
            await second.hangup()
            self.assertGreaterEqual(time.monotonic() - started, 0.2)  # 5 per second


class SyncPhoneTest(unittest.TestCase):
    def test_same_api_without_await(self):
        with Phone(local("1001", "a", 46000), limits=Limits(max_calls=4)) as phone:
            other = phone.account(local("1002", "b", 46200))

            @other.on(AsyncPhone.Incoming)
            async def answer(event):
                await event.call.answer(media="echo")

            with phone.call(other.uri) as call:
                call.dtmf("1")
                event = call.wait_for(Call.Stats, lambda e: e.stats.rx_packets >= 10)
                self.assertGreaterEqual(event.stats.rx_packets, 10)
            self.assertTrue(call.report.answered)


class CompactHeadersTest(unittest.IsolatedAsyncioTestCase):
    async def invite_head(self, **settings):
        """The INVITE the phone sends, as text, with these settings."""
        async with AsyncPhone(replace(local("1001", "a", 46000), **settings)) as phone:
            other = await phone.account(user="1002")

            @other.on(AsyncPhone.Incoming)
            async def answer(event):
                await event.call.answer()

            async with phone.call(other.uri) as call:
                pass
        invite = next(
            m for m in call.trace if m.direction == "TX" and m.method == "INVITE"
        )
        self.assertEqual(call.state, "DISCONNECTED")
        return invite.raw.replace("\r\n", "\n")

    async def test_compact_form_is_sent_only_when_asked(self):
        compact = await self.invite_head(compact_headers=True)
        self.assertIn("\ni: ", compact)
        self.assertNotIn("\nCall-ID:", compact)
        full = await self.invite_head()  # the setting does not leak to the next phone
        self.assertIn("\nCall-ID:", full)


if __name__ == "__main__":
    unittest.main()
