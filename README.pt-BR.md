# simple-phone

*[English](README.md)*

Telefone SIP para testar chamadas, como comando e como biblioteca Python. O PJSIP 2.17 já vem compilado dentro do wheel, então não há nada para compilar.

## Instalar

Linux x86_64, Python 3.14 ou 3.15. A única biblioteca do sistema de que ele precisa é a ALSA, que todo desktop Linux tem.

```bash
pip install simple-phone                  # ou: uv add simple-phone
sudo apt install libasound2t64            # só se faltar a ALSA (libasound2 antes do Ubuntu 24.04)
pip install 'simple-phone[stt,tts]'       # opcional: Whisper e Piper para say() e listen()
```

Ou rode sem instalar, com o [uv](https://docs.astral.sh/uv/):

```bash
uvx simple-phone doctor --server pbx.example.com --user 1001   # REGISTER e OPTIONS
uvx simple-phone call 1002 --server pbx.example.com --user 1001
```

Confira a instalação e depois a sua conta:

```bash
simple-phone doctor                                       # esta máquina: codecs, dispositivos de áudio
simple-phone doctor --server pbx.example.com --user 1001  # também REGISTER e OPTIONS
```

## Usar pelo terminal

A senha vem de `$SIP_PASSWORD`, ou o comando pergunta.

```bash
export SIP_PASSWORD=...
# Liga, fica 30 s, desliga e mostra o relatório
simple-phone call 1002 --server pbx.example.com --user 1001 --duration 30
# Espera uma chamada e devolve o que ouve (eco)
simple-phone answer --server pbx.example.com --user 1002 --media echo --timeout 600
# Toca 5 s antes de atender, depois eco após 3 s de silêncio
simple-phone answer --server pbx.example.com --user 1002 --answer-delay 5 --media echo --media-delay 3
# Envia um tom de 1 kHz, ou ruído tão alto quanto a fala
simple-phone call 1002 --server pbx.example.com --user 1001 --media tone --tone 1000
simple-phone call 1002 --server pbx.example.com --user 1001 --media noise
# Digita teclas 2 s depois do atendimento (DTMF RFC 4733)
simple-phone call 600 --server pbx.example.com --user 1001 --dtmf '1234#' --dtmf-delay 2
# Toca um WAV (8 kHz mono) em loop e grava o que volta
simple-phone call 1002 --server pbx.example.com --user 1001 --media wav --wav aviso.wav --loop --record volta.wav
# Conversa: microfone e alto-falante
simple-phone call 1002 --server pbx.example.com --user 1001 --media mic --speaker
# Mostra cada mensagem SIP e os contadores RTP enquanto acontecem
simple-phone call 1002 --server pbx.example.com --user 1001 --trace --stats
# Sem conta: liga direto para um host, faz ping, manda uma mensagem
simple-phone call 1002@192.0.2.10
simple-phone options pbx.example.com
simple-phone message 1002@pbx.example.com olá
# Dispositivos de áudio, para --set capture_device=N
simple-phone devices
```

`call` mostra o status SIP, o tempo até o atendimento e perda, jitter, RTT e MOS de cada fluxo RTP. `call` e `answer` saem com 0 quando a chamada foi atendida com áudio, então servem em scripts:

```bash
simple-phone call 1002 --profile conta.json --json relatorio.json && echo "rota ok"
```

Guarde uma conta num arquivo JSON e passe `--profile`: há exemplos para PABX, trunk, NAT e um atendedor de teste em [examples/accounts/](examples/accounts/) e [docs/cli.pt-BR.md#perfis](docs/cli.pt-BR.md#perfis).

Todas as opções, o relatório e os códigos de saída: [docs/cli.pt-BR.md](docs/cli.pt-BR.md).

## Usar pelo Python

```python
import asyncio
from simple_phone import AsyncPhone


async def main():
    async with AsyncPhone(server="pbx", user="1001", password="...") as phone:
        async with phone.call("1002") as call:
            await call.dtmf("1234#")
        print(call.trace.flow())  # ['INVITE', '100', '180', '200', 'ACK', 'BYE', '200']
        print(call.report.mos)


asyncio.run(main())
```

`Phone` é a mesma API sem `await`:

```python
from simple_phone import Phone

with Phone(server="pbx.example.com", user="1001", password="...") as phone:
    with phone.call("1002") as call:
        call.dtmf("1234#")
```

Atender chamadas e reagir a eventos:

```python
from simple_phone import AsyncPhone, Call

async with AsyncPhone(server="pbx.example.com", user="1002", password="...") as phone:

    @phone.on(AsyncPhone.Incoming)
    async def incoming(event):
        await event.call.answer(media="echo")

    @phone.on(Call.Dtmf, digit="#")
    async def done(event):
        await event.call.hangup()

    await phone.serve()
```

Conferir uma rota num teste:

```python
async with phone.call("1002") as call:
    event = await call.wait_for(Call.Stats, lambda e: e.stats.rx_packets >= 100)
    assert event.stats.rx_loss_percent < 1
assert call.report.mos >= 3.8
```

O resto da API: [docs/api.pt-BR.md](docs/api.pt-BR.md). Exemplos que rodam numa máquina só, sem PABX: [examples/api/](examples/api/README.md).

## O que faz

- Registra um ramal, ou usa um trunk sem registro.
- Faz e atende chamadas por UDP ou TCP, com G.711 por padrão.
- Envia silêncio, o eco do que ouve, um arquivo WAV ou o microfone. Grava o que recebe.
- Envia e recebe DTMF por RFC 4733, SIP INFO ou tons no áudio.
- Relata por chamada cada mensagem SIP, perda, jitter, RTT e um MOS estimado.
- Diz quem atendeu uma chamada feita: uma pessoa, uma URA, a caixa postal ou um anúncio da rede.
- Põe em espera, transfere e junta chamadas em conferência.
- Assina presença, BLF e caixa postal (MWI). Envia OPTIONS, MESSAGE e texto em tempo real.
- Roda até 64 chamadas num processo, no ritmo definido por `Limits`.
- Fala e transcreve com Piper e Whisper.

## Documentação

- [docs/cli.pt-BR.md](docs/cli.pt-BR.md): o comando, as opções e o relatório.
- [docs/api.pt-BR.md](docs/api.pt-BR.md): a API Python.
- [docs/development.pt-BR.md](docs/development.pt-BR.md): build, testes, CI e publicação.
- [docs/architecture.pt-BR.md](docs/architecture.pt-BR.md): como o código é organizado.
- [CHANGELOG.md](CHANGELOG.md): o que mudou em cada versão.

## Licença

GPL-2.0-or-later. O PJSIP é GPL e vai linkado dentro deste pacote, então o pacote tem a mesma licença. A Teluu vende licença comercial do PJSIP para uso em software fechado.
