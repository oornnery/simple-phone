"""Presence, BLF, typing, real-time text (RTT) and a rejected INVITE.

    python 12_presence_text.py

On a PBX, `subscribe(extension, dialog=True)` brings Phone.DialogState
instead (BLF: terminated = idle, early = ringing, confirmed = on a call).
Nothing here answers a dialog SUBSCRIBE, so only presence shows up.
"""

import asyncio

from simple_phone import AsyncPhone, CallFailed


async def main():
    async with AsyncPhone(
        server="127.0.0.1", user="1001", register=False, text=True
    ) as phone:
        far = await phone.account(user="1002")  # the far end: a second account here

        # Presence: far watches phone
        @far.on(AsyncPhone.Presence)
        def presence(event):
            print("[far] presence of", event.uri, event.online, event.note)

        @far.on(AsyncPhone.Typing)
        def typing(event):
            print("[far]", event.from_uri, "typing" if event.typing else "stopped")

        await far.subscribe(phone.uri)
        await phone.set_presence(True, "available")
        await phone.typing(far.uri)
        await asyncio.sleep(0.5)
        await far.unsubscribe(phone.uri)

        # RTT: both sides need text=True (accounts inherit it); text goes letter by letter
        writer = await phone.account(user="1003")

        answered = []

        @phone.on(AsyncPhone.Incoming)
        async def answer(event):
            answered.append(event.call)
            await event.call.answer()

        async with writer.call(phone.uri) as call:
            for char in "hello, worlx\bd":  # \b deletes, as on a keyboard
                await call.send_text(char)
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.3)
        print("RTT received:", repr(answered[0].text_received))

        # An INVITE PJSUA rejects before it becomes a Call (unknown Require)
        @far.on(AsyncPhone.Rejected)
        def rejected(event):
            print("[far] rejected:", event.code, event.reason)

        try:
            async with phone.call(far.uri, headers={"Require": "foo"}):
                pass
        except CallFailed as error:
            print("Call:", error)
        await asyncio.sleep(0.2)


asyncio.run(main())
