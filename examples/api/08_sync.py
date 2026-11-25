"""The same API without async/await: Phone (like httpx.Client next to AsyncClient).

Handlers can still be `async def`: they run on Phone's internal loop.
"""

import time

import local

from simple_phone import Call, Phone

with Phone(local.settings()) as phone:
    far = phone.account(local.settings("1002", 40200))

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
