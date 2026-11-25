"""The same API without async/await: Phone (like httpx.Client next to AsyncClient).

Handlers can still be `async def`: they run on Phone's internal loop.
"""

import time

from simple_phone import Call, Phone

with Phone(server="127.0.0.1", user="1001", register=False) as phone:
    far = phone.account(user="1002")  # the far end: a second account here

    @far.on(Phone.Incoming)
    async def answer(event):
        await event.call.answer(media="echo")

    print("OPTIONS:", phone.options(far.uri).code)
    with phone.call(far.uri) as call:
        call.dtmf("1234#")
        event = call.wait_for(Call.Stats, lambda e: e.stats.rx_packets >= 50)
        print("Packets received:", event.stats.rx_packets)
        time.sleep(1)
    print("MOS:", call.report.mos)
