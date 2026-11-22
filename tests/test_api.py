import asyncio
import contextlib
import time
import unittest
from dataclasses import replace

from simple_phone import (
    AsyncPhone,
    Call,
    CallFailed,
    Limits,
    Phone,
    PhoneError,
    PoolTimeout,
    Settings,
    Timeouts,
    WaitTimeout,
)


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


class Answering(AsyncPhone):
    """Handlers as methods, like Textual: on_<namespace>_<event>."""

    async def on_phone_incoming(self, event):
        await event.call.answer(media="echo")


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
        self.assertEqual((await self.phone.message(self.other.uri, "olá")).code, 200)
        await asyncio.sleep(0.2)
        self.assertEqual([m.body for m in received], ["olá"])

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
        self.phone.on(Call.Insight)(seen.append)
        async with self.phone.call(third.uri) as call:
            self.assertTrue((await call.hold()).held)
            self.assertFalse((await call.unhold()).held)  # right after hold()
            call.emit(Call.Insight(text="olá", output="greeting"))
            event = await call.wait_for(Call.Insight)
        self.assertIs(event.call, call)
        self.assertEqual([e.output for e in seen], ["greeting"])
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
        self.assertEqual(answered[0].evidence.text_received, "ola")

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
        await self.phone.set_presence(False, "em reunião")
        await until(lambda: presence[-1].online is False)
        self.assertEqual(presence[-1].note, "em reunião")
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


class SubclassTest(unittest.IsolatedAsyncioTestCase):
    async def test_on_methods_and_limits(self):
        limits = Limits(max_calls=1, calls_per_second=5)  # one dialed call at once
        async with Answering(local("1001", "a", 46000), limits=limits) as phone:
            caller = await phone.account(local("1002", "b", 46200))
            started = time.monotonic()
            first = await caller.dial(phone.uri)  # answered by on_phone_incoming
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


if __name__ == "__main__":
    unittest.main()
