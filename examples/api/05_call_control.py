"""Call control: hold, conference, blind and attended transfer. Three
accounts: us (1001), 1002 and 1003, both answering with echo."""

import asyncio

import local

from simple_phone import AsyncPhone, Call


async def main():
    async with AsyncPhone(local.settings()) as phone:
        b = await local.far_end(phone, "1002")
        c = await local.far_end(phone, "1003")
        for far in (b, c):

            @far.on(AsyncPhone.Incoming)
            async def answer(event):
                await event.call.answer(media="echo")

            @far.on(Call.TransferRequest)
            def refer(event):
                print(f"[{event.phone.settings.user}] REFER to", event.target)

        # Hold
        async with phone.call(b.uri) as call:
            held = await call.hold()  # returns when the re-INVITE is answered
            print("On hold:", held.status)
            await call.unhold()

        # Conference and attended transfer: B ends up talking to C
        async with phone.call(b.uri) as to_b, phone.call(c.uri) as to_c:
            await to_b.conference(to_c)  # B and C hear each other
            await asyncio.sleep(1)
            await to_b.conference(to_c, enabled=False)
            await to_b.attended_transfer(to_c)  # REFER with Replaces
            status = await to_b.wait_for(Call.TransferStatus, lambda e: e.final)
            print("Attended:", status.code, status.reason, status.success)
            await to_c.ended(5)  # the leg to C was replaced
        # leaving the block hangs up the leg to B, as the REFER asks

        # Blind transfer: B calls C on its own
        async with phone.call(b.uri) as call:
            await call.transfer(c.uri)
            status = await call.wait_for(Call.TransferStatus, lambda e: e.final)
            print("Blind:", status.code, status.reason, status.success)


asyncio.run(main())
