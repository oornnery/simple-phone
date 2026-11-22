"""Sinalização: headers, mensagens SIP, OPTIONS/MESSAGE, INFO, UPDATE e o ladder.

`phone.request(método, destino)` manda qualquer requisição fora de chamada.
Um receptor PJSUA (como o daqui) não responde NOTIFY/INFO fora de chamada;
um PABX responde.
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

        @far.on(AsyncPhone.Message)  # MESSAGE fora de chamada
        @far.on(Call.Message)  # MESSAGE dentro da chamada
        def received(event):
            print("[outro lado] MESSAGE:", event.body)

        # Fora de chamada
        response = await phone.options(far.uri)
        print("OPTIONS:", response.code, response.reason)
        response = await phone.message(far.uri, "oi, fora da chamada")
        print("MESSAGE:", response.code)

        headers = {"P-Asserted-Identity": "<sip:1001@127.0.0.1>", "X-Campaign": "abc"}
        async with phone.call(far.uri, headers=headers) as call:
            invite = await call.wait_for(
                Call.Sip,
                lambda e: e.message.direction == "TX" and e.message.method == "INVITE",
            )
            print("INVITE com:", invite.message.headers["x-campaign"])
            print("200 OK de:", call.response.headers.get("contact"))

            # Dentro da chamada
            info = await call.request(
                "INFO",
                "Signal=5\r\nDuration=160\r\n",
                content_type="application/dtmf-relay",
            )
            print("INFO:", info.code, info.reason)
            await call.message("oi, dentro da chamada")
            await call.update()  # renova a sessão sem re-INVITE
            dump = await call.dump()  # diagnóstico do PJSUA: diálogo, SDP, mídia
            print("Dump:", dump.splitlines()[0].strip(), "...")

        print("Fluxo:", " ".join(call.trace.flow()))
        for message in call.trace:  # o ladder inteiro desta chamada
            arrow = "-->" if message.direction == "TX" else "<--"
            print(" ", arrow, message.label)


asyncio.run(main())
