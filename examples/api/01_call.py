"""Calling: a scoped call, DTMF, the report, a busy line, and each step by hand."""

import asyncio

import local

from simple_phone import AsyncPhone, CallFailed


async def main():
    async with AsyncPhone(local.settings()) as phone:
        far = await local.far_end(phone)
        busy = False

        @far.on(AsyncPhone.Incoming)
        async def answer(event):
            if busy:
                await event.call.reject(486)
            else:
                await event.call.answer(media="echo")

        # 1. Scoped: answered on entry (or CallFailed), hung up on exit.
        async with phone.call(far.uri) as call:
            print("Responses:", [m.label for m in call.history])
            await call.dtmf("1234#")
            await asyncio.sleep(2)
            print(f"Connected for {call.duration:.1f}s")
        report = call.report
        print(f"Report: {report.code} {report.reason}, MOS {report.mos}")

        # 2. Rejected: CallFailed carries the SIP code.
        busy = True
        try:
            async with phone.call(far.uri):
                pass
        except CallFailed as error:
            print("Rejected:", error.code, error.reason)

        # 3. Unscoped: every step is yours.
        busy = False
        call = await phone.dial(far.uri)  # returns at once, still ringing
        await call.answered(timeout=10)
        report = await call.hangup()
        print("Step by step:", report.answered, report.code)


asyncio.run(main())
