"""Accounts, registration and the endpoint.

    python 09_accounts.py                                  # local: accounts, audio, codecs
    SIP_PASSWORD=... python 09_accounts.py my-account.json  # registers with the PBX

A profile is JSON with the keyword arguments of AsyncPhone and, optionally,
`password_env` (default SIP_PASSWORD). There is one in ../accounts/pbx.json.
"""

import asyncio
import sys

from simple_phone import AsyncPhone, PhoneError


async def on_pbx(path):
    phone = AsyncPhone.from_profile(path, auto_register=False)  # we send REGISTER
    async with phone:

        @phone.on(AsyncPhone.Registration)
        def show(event):
            print(
                "REGISTER:", event.code, event.reason, "active" if event.active else ""
            )

        try:
            await phone.register()
        except PhoneError as error:  # RegistrationFailed (403...) or WaitTimeout
            print("Not registered:", error)
            return
        print("Registered as", phone.uri)
        await phone.unregister()


async def on_this_machine():
    async with AsyncPhone(server="127.0.0.1", user="1001", register=False) as phone:
        other = await phone.account(user="1002")  # another identity, same SIP port
        print("Accounts:", phone.uri, other.uri)
        print("Codecs:", [c["id"] for c in await phone.codecs()])
        print("Audio:", [d["name"] for d in await phone.devices()] or "none")
        await phone.configure(media="echo")  # default for the next calls
        await phone.ip_changed()  # after a network change (Wi-Fi, VPN)


if len(sys.argv) > 1:
    asyncio.run(on_pbx(sys.argv[1]))
else:
    asyncio.run(on_this_machine())
