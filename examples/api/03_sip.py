"""Signalling: headers, SIP messages, OPTIONS/MESSAGE, INFO, UPDATE and the ladder.

`phone.request(method, target)` sends any request outside a call. A PJSUA
receiver (like the one here) does not answer NOTIFY or INFO outside a call;
a PBX does.
"""

import asyncio

import local

from simple_phone import AsyncPhone, Call


async def main():
    async with AsyncPhone(local.settings()) as phone:
        far = await local.far_end(phone)

        @far.on(AsyncPhone.Incoming)
        async def answer(event):
            await event.call.answer(media="echo")

        @far.on(AsyncPhone.Message)  # MESSAGE outside a call
        @far.on(Call.Message)  # MESSAGE inside the call
        def received(event):
            print("[far end] MESSAGE:", event.body)

        # Outside a call
        response = await phone.options(far.uri)
        print("OPTIONS:", response.code, response.reason)
        response = await phone.message(far.uri, "hi, outside the call")
        print("MESSAGE:", response.code)

        headers = {"P-Asserted-Identity": "<sip:1001@127.0.0.1>", "X-Campaign": "abc"}
        async with phone.call(far.uri, headers=headers) as call:
            invite = await call.wait_for(
                Call.Sip,
                lambda e: e.message.direction == "TX" and e.message.method == "INVITE",
            )
            print("INVITE with:", invite.message.headers["x-campaign"])
            print("200 OK from:", call.response.headers.get("contact"))

            # Inside the call
            info = await call.request(
                "INFO",
                "Signal=5\r\nDuration=160\r\n",
                content_type="application/dtmf-relay",
            )
            print("INFO:", info.code, info.reason)
            await call.message("hi, inside the call")
            await call.update()  # refreshes the session without a re-INVITE
            dump = await call.dump()  # PJSUA's diagnostics: dialog, SDP, media
            print("Dump:", dump.splitlines()[0].strip(), "...")

        print("Flow:", " ".join(call.trace.flow()))
        for message in call.trace:  # the whole ladder of this call
            arrow = "-->" if message.direction == "TX" else "<--"
            print(" ", arrow, message.label)


asyncio.run(main())
