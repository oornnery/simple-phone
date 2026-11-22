"""Contas, registro e o endpoint.

    python 09_accounts.py                        # local: contas, áudio, codecs
    SIP_PASSWORD=... python 09_accounts.py minha-conta.json   # registra no PABX

Perfil JSON: campos de Settings e, opcional, `password_env` (padrão
SIP_PASSWORD). Exemplo em ../accounts/pbx.json.
"""

import asyncio
import sys

import local

from simple_phone import AsyncPhone, PhoneError


async def on_pbx(path):
    phone = AsyncPhone.from_profile(path, auto_register=False)  # o REGISTER é nosso
    async with phone:

        @phone.on(AsyncPhone.Registration)
        def show(event):
            print(
                "REGISTER:", event.code, event.reason, "ativo" if event.active else ""
            )

        try:
            await phone.register()
        except PhoneError as error:  # RegistrationFailed (403...) ou WaitTimeout
            print("Não registrou:", error)
            return
        print("Registrado como", phone.uri)
        await phone.unregister()


async def on_this_machine():
    async with AsyncPhone(local.settings()) as phone:
        other = await local.far_end(phone, "1002")  # outra identidade, mesma porta
        print("Contas:", phone.uri, other.uri)
        print("Codecs:", [c["id"] for c in await phone.codecs()])
        print("Áudio:", [d["name"] for d in await phone.devices()] or "nenhum")
        await phone.configure(media="echo")  # padrão das próximas chamadas
        await phone.ip_changed()  # trocou de rede (Wi-Fi, VPN): refaz o necessário


if len(sys.argv) > 1:
    asyncio.run(on_pbx(sys.argv[1]))
else:
    asyncio.run(on_this_machine())
