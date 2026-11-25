"""Receiving calls and reacting to events, three ways:

1. @phone.on(Type): one function per event type;
2. @phone.on(Type, attribute=value): with a filter;
3. async for event in phone.events(Type): a stream.

On a real extension, end with `await extension.serve()` (runs until Ctrl+C).
"""

import asyncio

import local

from simple_phone import AsyncPhone, Call


async def main():
    async with AsyncPhone(local.settings("1002", 40200)) as extension:
        phone = await extension.account(local.settings("1001", 40000))

        @extension.on(AsyncPhone.Incoming)
        async def incoming(event):
            print("[extension] call from", event.remote_uri)
            await event.call.answer(183)  # early media: audio before the answer
            await asyncio.sleep(0.5)
            await event.call.answer(media="echo")

        @extension.on(Call.Dtmf)
        def digit(event):
            print("[extension] got", event.digit, f"({event.method})")

        @extension.on(Call.Dtmf, digit="#")  # only '#'
        async def hang_up(event):
            await event.call.hangup()

        @extension.on(Call.Ended)
        def ended(event):
            print("[extension] ended:", event.report.code, event.report.reason)

        async def show_states():
            async for event in phone.events(Call.StateChanged):
                print("[caller] state:", event.state, event.code)

        watcher = asyncio.create_task(show_states())
        call = await phone.dial(extension.uri)
        await call.answered()
        await call.dtmf("12#")
        report = await call.ended(timeout=10)  # the extension hangs up on '#'
        print("Answered:", report.answered, "| flow:", " ".join(call.trace.flow()))
        watcher.cancel()


asyncio.run(main())
