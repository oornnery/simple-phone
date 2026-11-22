"""Against a real PBX: the Asterisk of tests/asterisk (bash scripts/asterisk.sh).

Skipped unless ASTERISK_HOST is set, e.g. ASTERISK_HOST=127.0.0.1.
"""

import asyncio
import os
import unittest
from dataclasses import replace

from simple_phone import (
    AsyncPhone,
    Call,
    CallFailed,
    DigestAuth,
    RegistrationFailed,
    Settings,
)

HOST = os.environ.get("ASTERISK_HOST")


def account(user, rtp_port, **fields):
    return Settings(
        server=HOST or "127.0.0.1",
        user=user,
        account_id=user,
        local_port=5070,
        rtp_port=rtp_port,
        log_level=0,
        **fields,
    )


async def until(condition, timeout=10):
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.05)


@unittest.skipUnless(HOST, "set ASTERISK_HOST (bash scripts/asterisk.sh)")
class AsteriskTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.phone = AsyncPhone(
            account("1001", 42000, mwi=True), auth=DigestAuth(password="secret")
        )
        await self.phone.__aenter__()  # registered, or raises
        self.addAsyncCleanup(self.phone.close)
        self.other = await self.phone.account(
            account("1002", 42200), auth=DigestAuth(password="secret")
        )

    async def test_registration_and_options(self):
        self.assertTrue(self.phone.registered)
        self.assertTrue(self.phone.reg.startswith("200"))
        # PJSUA sends OPTIONS without credentials; Asterisk challenges 1001
        response = await self.phone.options(f"sip:{HOST}:5060")
        self.assertIn(response.code, (200, 401))

    async def test_wrong_password_is_rejected(self):
        wrong = replace(account("1002", 42400), account_id="wrong")
        with self.assertRaises(RegistrationFailed):
            await self.phone.account(wrong, auth=DigestAuth(password="nope"))

    async def test_echo_carries_rtp_both_ways(self):
        async with self.phone.call("600") as call:
            stats = await call.wait_for(Call.Stats, lambda e: e.stats.rx_packets >= 50)
        self.assertEqual(stats.stats.codec, "PCMA")
        self.assertTrue(call.report.answered)
        self.assertIn("INVITE", call.trace.flow())

    async def test_dtmf_from_the_pbx(self):
        call = await self.phone.dial("601")
        await call.answered()
        await call.ended(timeout=10)
        self.assertEqual(call.dtmf_received, "123")

    async def test_busy(self):
        with self.assertRaises(CallFailed) as failed:
            async with self.phone.call("602"):
                pass
        self.assertEqual(failed.exception.code, 486)

    async def test_extension_to_extension_with_blf(self):
        states = []
        self.phone.on(AsyncPhone.DialogState)(lambda e: states.append(e.state))
        await self.phone.subscribe("1002", dialog=True)
        await until(lambda: states)  # the first NOTIFY: idle

        @self.other.on(AsyncPhone.Incoming)
        async def answer(event):
            await asyncio.sleep(1)  # ring a little: BLF shows "early"
            await event.call.answer(media="echo")

        async with self.phone.call("1002") as call:
            await call.dtmf("5")
            await asyncio.sleep(0.5)
        self.assertEqual(states[0], "terminated")
        self.assertIn("early", states)
        await until(lambda: states[-1] == "terminated")

    async def test_voicemail_notify(self):
        mwi = []
        self.phone.on(AsyncPhone.Mwi)(mwi.append)
        await self.phone.register()  # a new REGISTER makes the PBX send MWI
        await until(lambda: mwi)
        self.assertIn("Voice-Message", mwi[-1].body)


if __name__ == "__main__":
    unittest.main()
