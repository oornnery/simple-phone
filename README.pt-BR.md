# simple-phone

*[English](README.md)*

Telefone SIP para testar chamadas, feito sobre o PJSUA2 (PJSIP 2.17), que já vem compilado dentro do wheel. Tem duas partes:

- **Comando `simple-phone`:** registra um ramal (ou usa um trunk sem registro), faz ou atende uma chamada e mostra o relatório de SIP e RTP/RTCP.
- **API Python:** `AsyncPhone`, e `Phone` com os mesmos métodos sem `await`. Serve para automação de testes, bots de voz e testes de carga.

Plataforma: Linux x86_64, Python 3.14. Transportes: UDP e TCP; TLS exige um build com `PJSIP_TLS=1`. Codecs padrão: G.711 PCMA e PCMU.

## Instalar

```bash
uv tool install simple-phone    # o comando
pip install simple-phone        # a biblioteca
pip install 'simple-phone[stt,tts]'   # voz: faster-whisper e Piper
```

A única dependência do sistema é a ALSA, que todo desktop Linux já tem. Em servidor ou container mínimo:

```bash
sudo apt install -y libasound2t64    # Debian 13, Ubuntu 24.04+
sudo apt install -y libasound2       # Debian 12, Ubuntu 22.04
sudo pacman -S --needed alsa-lib     # Arch
```

## Linha de comando

```bash
simple-phone call 1002 --server pbx.example.com --user 1001 --media echo --duration 30
simple-phone answer --server pbx.example.com --user 1002 --media echo --timeout 600
simple-phone doctor --server pbx.example.com --user 1001
simple-phone devices
```

`call` registra, disca, fica conectado por `--duration` segundos, desliga e mostra um resumo. A chamada também termina antes se o outro lado desligar ou se você apertar Ctrl+C. `answer` espera até `--timeout` segundos por uma chamada. `doctor` confere versões, codecs, dispositivos de áudio, NAT (quando há `stun_servers`), REGISTER e um OPTIONS. `devices` lista os dispositivos de áudio.

A senha vem de `$SIP_PASSWORD` ou é pedida no terminal:

```bash
read -rs SIP_PASSWORD && export SIP_PASSWORD   # não fica no histórico do shell
```

Trunk autenticado por IP, com um header extra:

```bash
simple-phone call sip:5511999990001@192.0.2.20 --server 192.0.2.20 --user 551130000000 \
  --no-register --header 'P-Asserted-Identity: <sip:551130000000@192.0.2.10>'
```

Teste de ponta a ponta: rode `answer --media echo` em um host. Em outro, envie um WAV e grave o que volta:

```bash
simple-phone call 1002 --server pbx --user 1001 --media wav --wav reference.wav \
  --record volta.wav --dtmf '1234#'
```

`volta.wav` traz o seu próprio áudio, e o receptor mostra os dígitos DTMF que chegaram. Uma chamada cobre sinalização, áudio nos dois sentidos e DTMF.

### Opções

| Opção | Significado | Padrão |
|---|---|---|
| `--server`, `--user` | Registrador ou host do trunk, e o ramal | obrigatório (ou `--profile`) |
| `--port` | Porta do registrador | 5060 |
| `--auth-user` | Login Digest, quando diferente de `--user` | `--user` |
| `--domain` | Domínio da identidade SIP | `--server` |
| `--proxy` | Proxy de saída, ex.: `'sip:10.0.0.1:5060;lr'` (aspas por causa do `;`) | nenhum |
| `--no-register` | Sem REGISTER (trunk autenticado por IP) | registra |
| `--transport` | `udp`, `tcp` ou `tls` | udp |
| `--local-port`, `--rtp-port` | Porta SIP local; primeira de 100 portas RTP | 5070, 40000 |
| `--profile ARQUIVO` | JSON com quaisquer campos de `Settings`, mais `password_env` | |
| `--password-env` | Variável com a senha | `SIP_PASSWORD` |
| `--set NOME=VALOR` | Qualquer outro campo de `Settings`, ex.: `--set srtp=mandatory` | |
| `--media` | `silent`, `echo`, `wav` ou `mic` | silent |
| `--wav`, `--record` | WAV a enviar; WAV para gravar o que chega | |
| `--listen` | Toca o áudio recebido nesta máquina | desligado |
| `--codec` | `auto`, ou nomes como `PCMA,PCMU,opus` | auto |
| `--no-amd` | Desliga a detecção de secretária eletrônica | ligado |
| `--duration` | Segundos conectado (`call`, `answer`) | 15 |
| `--timeout` | Limite para o REGISTER, o atendimento e a espera por chamada | 30 |
| `--header 'Nome: valor'` | Header extra no INVITE, repetível (`call`) | |
| `--dtmf`, `--dtmf-delay` | Dígitos RFC 4733, enviados tantos segundos após o atendimento (`call`) | nenhum, 2 |
| `--json ARQUIVO` | Salva o relatório completo | |
| `--trace`, `--stats`, `-v` | Uma linha por mensagem SIP; contadores RTP a cada segundo; log do PJSIP | desligado |

As flags têm precedência sobre o perfil, e `--set` sobre os dois. `--set` lê valores JSON: números, `true`/`false`, listas.

### Modos de mídia

| Modo | O que envia |
|---|---|
| `silent` | Silêncio. O RTP continua fluindo (padrão) |
| `echo` | O áudio que recebe, decodificado e codificado de novo |
| `wav` | O `--wav` uma vez, depois silêncio. PCM 16 bits, mono, 8 kHz |
| `mic` | O microfone |

```bash
ffmpeg -f lavfi -i "sine=frequency=1000:sample_rate=8000:duration=60" -ac 1 -c:a pcm_s16le reference.wav
ffmpeg -i fala.mp3 -ar 8000 -ac 1 -c:a pcm_s16le reference.wav
```

### Resultados

O resumo mostra o resultado, o status SIP final, o Call-ID, o tempo até o atendimento, o tempo conectado e o veredito do AMD. Abaixo vem uma linha da tabela por stream RTP e sentido: codec, endereço remoto, pacotes, perdas, jitter, RTT e MOS estimado.

| Resultado | Código de saída | Significado |
|---|---|---|
| `ANSWERED` | 0 | Atendida, com stream de áudio |
| `NO MEDIA` | 1 | 200 OK sem stream de áudio: em geral, nenhum codec em comum |
| `FAILED` | 1 | Não registrou, não foi atendida ou houve erro |
| `INTERRUPTED` | 130 | Ctrl+C |

```bash
simple-phone call 1002 --server pbx --user 1001 --json r.json && echo "rota ok"
```

Como ler os números:

- `ANSWERED` não prova que o áudio era audível: o RTP pode transportar silêncio. Grave e ouça, ou use o teste de ponta a ponta.
- RX é o que este lado recebeu. Perda e jitter de TX vêm do RTCP do outro lado.
- RTT é a ida e volta medida pelo RTCP, não o atraso do áudio em um sentido.
- `-` (ou `null` no JSON) significa sem amostra, não zero.
- O MOS é uma estimativa de rede: o modelo E (ITU-T G.107) aplicado a perda, jitter e RTT com parâmetros de G.711. Ele não analisa o áudio e tem teto perto de 4,4. Use-o para comparar rotas.
- Um re-INVITE que recria um stream gera uma nova entrada (`stream 0.2`).

O relatório JSON traz também os eventos SIP e de registro com horário UTC, os DTMF recebidos e os avisos. A senha nunca é gravada. Números e identificadores são, então revise antes de compartilhar.

### Quem atendeu (AMD)

Toda chamada feita é classificada enquanto acontece, em três camadas:

1. **SIP:** atender em menos de 1 s, sem 18x, indica máquina.
2. **Padrão de fala**, como o `AMD()` do Asterisk: um "alô?" curto seguido de silêncio é `human`. Fala de mais de 1,5 s, ou 3 palavras seguidas, é `machine` (URA ou saudação de caixa postal).
3. **Tons** (Goertzel): tons SIT (913,8, 1370,6 e 1776,7 Hz), mesmo em early media, dão `sit`. Um bipe puro depois do atendimento dá `voicemail`.

| Resultado | Significado |
|---|---|
| `human` | Saudação curta, depois esperou |
| `machine` | URA ou saudação gravada |
| `voicemail` | Bipe de caixa postal |
| `sit` | Anúncio da rede (ex.: número inexistente) |
| `silence` | Ninguém falou em 2,5 s |
| `unsure` | Sem decisão em 5 s |

Os limiares são os padrões do Asterisk e só foram conferidos com áudio sintético. Calibre com gravações do seu tráfego antes de confiar no resultado. Música de espera, ruído e saudações humanas longas confundem a camada 2. Chamadas recebidas não são classificadas.

## API Python

```python
import asyncio
from simple_phone import AsyncPhone, Call, DigestAuth, Settings


async def main():
    settings = Settings(server="pbx.example.com", user="1001")
    async with AsyncPhone(settings, auth=DigestAuth(password="...")) as phone:
        # atendida aqui, ou levanta CallFailed (486...)
        async with phone.call("1002") as call:
            print((await call.amd()).result)  # human, machine, voicemail, sit...
            await call.dtmf("1234#")
        print(call.trace.flow())  # INVITE 100 180 200 ACK BYE 200
        print(call.report.mos)


asyncio.run(main())
```

`AsyncPhone` é uma conta SIP. `await phone.account(...)` adiciona outra conta no mesmo endpoint. `Phone` tem a mesma API sem `await`, como `httpx.Client` e `httpx.AsyncClient`. `Limits(max_calls, calls_per_second)` controla o ritmo do que `dial()` e `dial_all()` enviam, e `Timeouts` define as esperas padrão.

**Eventos tipados.** Os principais são `Call.StateChanged`, `Call.Answered`, `Call.Ended`, `Call.Sip`, `Call.Dtmf`, `Call.Stats`, `Call.Amd`, `Call.Transaction`, `Call.TransferRequest`, `Call.Text`, `AsyncPhone.Incoming`, `AsyncPhone.Registered`, `AsyncPhone.Message`, `AsyncPhone.Presence`, `AsyncPhone.DialogState` e `AsyncPhone.Mwi`. Há quatro formas de consumi-los:

```python
@phone.on(Call.Dtmf, digit="#")  # decorador com filtro
async def fim(event):
    await event.call.hangup()


class Ramal(AsyncPhone):  # métodos on_<grupo>_<evento>
    async def on_phone_incoming(self, event):
        await event.call.answer(media="echo")


async for event in call.events(Call.Sip, Call.Dtmf):  # stream
    ...
await call.wait_for(Call.Sip, lambda e: e.message.code == 183)  # espera
```

**Chamadas:**

- Atendimento: `answer(183)` (early media), `reject`, `hangup`.
- DTMF: `dtmf`, por RFC 4733, SIP INFO ou tons dentro do áudio.
- Controle: `hold` e `unhold` (cada um volta quando o re-INVITE é respondido), `transfer`, `attended_transfer(outra)`, `conference(outra)`, `update`, `mute`, `gain`.
- Requisições: `request("INFO", ...)` e `message` dentro da chamada.
- Texto em tempo real: `send_text` (RTT, RFC 4103, com `Settings(text=True)`).
- Inspeção: `history`, `response`, `trace`, `evidence`, `duration`, `dump()`.
- Eventos seus: `emit(event)`.

**Phone:**

- Chamadas: `dial`, `call` (gerenciador de contexto), `dial_all(destinos, handler)`, `incoming()`.
- Requisições fora de diálogo: `options`, `message`, `request` para qualquer método. O PJSUA as envia sem credenciais, então um PABX que as desafia responde 401.
- Registro: `register` e `unregister`.
- Presença e BLF: `subscribe(uri)` gera eventos `Presence`; `subscribe(uri, dialog=True)` gera eventos `DialogState` no lugar (livre, tocando, em chamada). Também `set_presence` e `typing`.
- Rede: `nat_type()` e `ip_changed()`.

**Settings:** `prack` (100rel), `session_timer` (RFC 4028), `mwi=True` (caixa postal como eventos `Mwi`), `follow_redirects`, `accept_transfers`, `srtp`, `ice`, `stun_servers`. Sem servidor, `Settings(register=False)` e `phone.uri` deixam duas contas locais ligarem uma para a outra.

**Mídia** (`simple_phone.media`):

```python
from simple_phone.media import PiperTTS, Recorder, Speaker, WavFile, WhisperSTT

tts, stt = PiperTTS("pt_BR-faber-medium"), WhisperSTT("base")
phone = AsyncPhone(settings, tts=tts, stt=stt)
async with phone.call("1002") as call:
    # o que transmite; troca a qualquer momento
    await call.send(WavFile("aviso.wav", loop=True))
    # para onde vai o áudio recebido
    await call.receive(Speaker(), Recorder("entrada.wav"))
    # para quando o outro lado começa a falar
    await call.say("Para segunda via, digite 1.", interrupt=True)
    opcao = await call.gather(length=1, timeout=5)  # DTMF recebido
    texto = await call.listen(timeout=10)  # a próxima frase, transcrita
    async for frame in call.audio():  # frames PCM brutos
        ...
```

STT e TTS são protocolos: serve qualquer objeto com `transcribe(pcm, rate)` ou `synthesize(text)`. Os [exemplos](examples/README.md) rodam numa máquina só, sem PABX.

## Usar o PJSUA2 direto

O binding pode ser importado:

```python
from simple_phone import pjsua2 as pj
```

Este build aceita 64 chamadas por processo; o padrão do PJSIP é 4. Para o ciclo de vida do endpoint, callbacks, estatísticas e a ordem de encerramento, veja `src/simple_phone/core/`. Duas regras valem para qualquer código Python sobre PJSUA2:

- Guarde `info = call.getInfo()` numa variável antes de percorrer `info.media`. Sem isso, os itens apontam para memória liberada.
- Nenhum `Call`, `Account` ou `Buddy` pode viver depois de `libDestroy()`.

## Áudio no WSL

Só é preciso para `--media mic` e `--listen`. O WSLg fornece PulseAudio, que a ALSA alcança pelo plugin `pulse`:

```bash
sudo apt install -y libasound2-plugins alsa-utils pulseaudio-utils
export PULSE_SERVER=unix:/mnt/wslg/PulseServer
pactl info
```

Se aparecer `PJMEDIA_EAUD_NODEFDEV`, escreva isto em `alsa-wslg.conf`:

```text
</usr/share/alsa/alsa.conf>
pcm.!default { type pulse }
ctl.!default { type pulse }
```

E rode o comando com `ALSA_CONFIG_PATH="$PWD/alsa-wslg.conf" simple-phone ...`.

## Docker

```dockerfile
FROM python:3.14-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends libasound2t64 \
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir simple-phone
ENTRYPOINT ["simple-phone"]
```

```bash
docker run --rm --network host -e SIP_PASSWORD simple-phone call 1002 --server pbx --user 1001
```

Use a rede do host. Numa rede bridge, o SDP continua anunciando o endereço do container, e publicar portas não muda isso.

## Problemas comuns

| Sintoma | Verificação |
|---|---|
| `libasound.so.2: cannot open shared object file` | Instalar a ALSA (veja Instalar) |
| `REGISTER rejected: 401` ou `403` | Login, senha, domínio, política do PABX |
| `REGISTER: nothing within 30s` | Endereço, porta, UDP liberado, firewall |
| `NO MEDIA`, 488 ou 415 | Codecs em comum, política de SRTP, a oferta SDP |
| RTP nos dois sentidos, mas silêncio | Grave e ouça: os pacotes podem transportar silêncio |
| `DTMF not sent` | O outro lado não negociou `telephone-event` |
| `PJMEDIA_EAUD_NODEFDEV` | Plugins ALSA e dispositivo padrão (veja WSL) |

## Desenvolvimento

Veja [docs/development.pt-BR.md](docs/development.pt-BR.md) para compilar o PJSIP, rodar os testes (inclusive contra o Asterisk em Docker), o CI e as publicações. Veja [docs/architecture.pt-BR.md](docs/architecture.pt-BR.md) para a organização do código.

## Licença

GPL-2.0-or-later. O PJSIP é GPL v2 ou posterior e vai linkado dentro deste pacote, então o pacote tem a mesma licença. A Teluu vende licença comercial do PJSIP para uso em software fechado.
