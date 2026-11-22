"""Uma URA de verdade, do lado que atende: fala com Piper e lê o teclado.

    pip install 'simple-phone[tts]'
    python 10_ivr_server.py        # SIP 5072; Ctrl+C sai

Ligue de outro terminal (11_listen.py ou um softphone) para sip:1002@127.0.0.1:5072. say(interrupt=True) para de
falar quando quem ligou começa a falar (barge-in).
"""

import asyncio
import contextlib

from simple_phone import AsyncPhone, Settings
from simple_phone.media import PiperTTS

MENU = (
    "Olá. Para segunda via da fatura, digite 1. Para falar com um atendente, digite 9."
)


class Ura(AsyncPhone):
    async def on_phone_incoming(self, event):
        call = event.call
        await call.answer()
        await asyncio.sleep(0.5)
        for _ in range(3):
            await call.say(MENU, interrupt=True)
            match await call.gather(length=1, timeout=6):
                case "1":
                    await call.say("Digite o seu CPF e, em seguida, tecle cerquilha.")
                    cpf = await call.gather(finish_on="#", timeout=20)
                    print("CPF recebido:", cpf)
                    await call.say(
                        "Pronto. A segunda via foi enviada para o seu e-mail. Obrigado."
                    )
                    break
                case "9":
                    await call.say("Transferindo para um atendente.")
                    break
                case "":
                    await call.say("Não recebi nenhuma opção.")
                case _:
                    await call.say("Opção inválida.")
        await call.hangup()


async def main():
    settings = Settings(
        server="127.0.0.1", user="1002", register=False, local_port=5072, rtp_port=42000
    )
    tts = PiperTTS("pt_BR-faber-medium")
    await tts.load()
    async with Ura(settings, tts=tts) as phone:
        print("URA em", phone.uri, "(Ctrl+C sai)")
        await phone.serve()


with contextlib.suppress(KeyboardInterrupt):
    asyncio.run(main())
