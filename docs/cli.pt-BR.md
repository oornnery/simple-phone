# Linha de comando

*[English](cli.md)*

```bash
simple-phone call 1002 --server pbx.example.com --user 1001 --media echo --duration 30
simple-phone answer --server pbx.example.com --user 1002 --media echo --timeout 600
simple-phone doctor --server pbx.example.com --user 1001
simple-phone options pbx.example.com
simple-phone message 1002 'olá' --server pbx.example.com --user 1001
simple-phone devices
simple-phone amd gravacao.wav
```

- `call` registra, disca, fica conectado por `--duration` segundos, desliga e mostra um resumo. A chamada termina antes se o outro lado desligar ou se você apertar Ctrl+C.
- `answer` espera até `--timeout` segundos por uma chamada e depois faz o mesmo.
- `doctor` confere versões, codecs, dispositivos de áudio, NAT (quando há `stun_servers`), REGISTER e um OPTIONS. Sem `--server`, confere só esta máquina.
- `options` e `message` enviam uma requisição fora de chamada e mostram a resposta, como o curl: linha de status, headers e corpo. Saem com 0 em qualquer resposta e com 1 quando nenhuma chega. O PJSUA as envia sem credenciais, então um PABX que as desafia responde 401.
- `devices` lista os dispositivos de áudio.
- `amd` passa um WAV gravado (16 bits, qualquer taxa) pela detecção de secretária eletrônica, offline, e mostra cada decisão com o motivo. Veja [Quem atendeu](#quem-atendeu-amd).

Um destino é um número (`1002`, que vira `sip:1002@<domínio>`), `usuário@host`, um host (`pbx.example.com`, `host:5060`) ou uma URI `sip:`.

Sem conta, basta o destino, como no curl:

```bash
simple-phone options pbx.example.com
simple-phone call 1002@192.0.2.10        # disca direto para o host
simple-phone answer --media echo         # espera em sip:simple-phone@127.0.0.1:5070
```

Sem `--server` e sem `--profile`, o usuário do `From` é `simple-phone`, nada é registrado e o servidor é o host do destino (no `answer`, esta máquina). `options` e `message` só registram quando o perfil ou `--set register=true` pede.

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

## Opções

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
| `--compact-headers` | Envia os nomes de header na forma compacta (`i:`, `f:`, `v:`...) | desligado |
| `--set NOME=VALOR` | Qualquer outro campo de `Settings`, ex.: `--set srtp=mandatory` | |
| `--media` | `silent`, `echo`, `wav`, `mic`, `tone` ou `noise` | silent |
| `--tone HZ` | Frequência do `--media tone` | 1000 |
| `--loop` | Repete o `--wav` em vez de tocar uma vez | desligado |
| `--wav`, `--record` | WAV a enviar; WAV para gravar o que chega | |
| `--speaker` | Toca o áudio recebido nesta máquina | desligado |
| `--codec` | `auto`, ou nomes como `PCMA,PCMU,opus` | auto |
| `--no-amd` | Desliga a detecção de secretária eletrônica | ligado |
| `--amd-initial-silence MS`, `--amd-greeting MS` | Limites do AMD; os outros com `--set amd_<nome>=...` (veja [AMD](#quem-atendeu-amd)) | 2500, 2000 |
| `--duration` | Segundos conectado (`call`, `answer`) | 15 |
| `--media-delay` | Segundos de silêncio depois do atendimento antes do `--media` começar (`call`, `answer`) | 0 |
| `--answer-delay` | Segundos tocando antes de o `answer` atender | 0 |
| `--timeout` | Segundos para registrar, para ser atendida e para esperar uma chamada | 30 |
| `--header 'Nome: valor'` | Header extra, repetível (`call`, `options`, `message`) | |
| `--dtmf`, `--dtmf-delay` | Dígitos RFC 4733, enviados tantos segundos após o atendimento (`call`, `answer`) | nenhum, 2 |
| `--json ARQUIVO` | Salva o relatório completo | |
| `--trace`, `--stats`, `-v` | Uma linha por mensagem SIP; contadores RTP a cada segundo; log do PJSIP | desligado |

As flags têm precedência sobre o perfil, e `--set` sobre os dois. `--set` lê valores JSON: números, `true`/`false`, listas.

## Perfis

Um perfil guarda uma conta num arquivo JSON: qualquer campo de `Settings`, mais `password_env`, o nome da variável que guarda a senha (padrão `SIP_PASSWORD`). A senha em si nunca vai no arquivo.

```json
{
  "account_id": "pbx",
  "server": "pbx.example.com",
  "user": "1001",
  "register": true,
  "password_env": "SIP_PASSWORD"
}
```

```bash
export SIP_PASSWORD=...
simple-phone call 1002 --profile pbx.json
simple-phone call 1002 --profile pbx.json --media echo --duration 60   # as opções valem mais que o perfil
simple-phone doctor --profile pbx.json
```

| Exemplo | Para |
|---|---|
| [pbx.json](../examples/accounts/pbx.json) | Um ramal registrado num PABX |
| [pbx-full.json](../examples/accounts/pbx-full.json) | Login Digest, domínio da identidade, proxy de saída, codecs, PRACK, session timer, MWI, seguir 3xx |
| [trunk.json](../examples/accounts/trunk.json) | Um trunk autenticado por IP: sem REGISTER |
| [nat.json](../examples/accounts/nat.json) | Atrás de NAT: TCP, STUN, ICE e SRTP quando o outro lado oferece |
| [answer-echo.json](../examples/accounts/answer-echo.json) | O lado que atende num teste: devolve e grava o que ouve |
| [local.json](../examples/accounts/local.json), [local-b.json](../examples/accounts/local-b.json) | Duas contas nesta máquina, sem PABX |

Pelo Python: `AsyncPhone.from_profile("pbx.json")`.

## Modos de mídia

| Modo | O que envia |
|---|---|
| `silent` | Silêncio. O RTP continua fluindo (padrão) |
| `echo` | O áudio que recebe, decodificado e codificado de novo |
| `wav` | O `--wav` uma vez, depois silêncio (`--loop` repete). PCM 16 bits, mono, 8 kHz |
| `mic` | O microfone |
| `tone` | Um tom senoidal contínuo de `--tone` Hz |
| `noise` | Ruído tão alto quanto a fala: o AMD ou a detecção de fala do outro lado o toma por alguém falando |

```bash
ffmpeg -f lavfi -i "sine=frequency=1000:sample_rate=8000:duration=60" -ac 1 -c:a pcm_s16le reference.wav
ffmpeg -i fala.mp3 -ar 8000 -ac 1 -c:a pcm_s16le reference.wav
```

## Resultados

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

## Quem atendeu (AMD)

Toda chamada feita é classificada enquanto acontece, em quatro camadas:

1. **SIP:** Atender em menos de 1 s, sem 18x, indica máquina.
2. **Padrão de fala**, como o `AMD()` do Asterisk: um "alô?" curto seguido de silêncio é `human`. Fala de mais de 2 s, ou 6 palavras seguidas, é `machine` (URA ou saudação de caixa postal).
3. **Tons** (Goertzel): tons SIT (913,8, 1370,6 e 1776,7 Hz), mesmo em early media, dão `sit`. Um bipe puro depois do atendimento dá `voicemail`.
4. **SIP com o áudio:** fala em early media (183) seguida de uma falha (4xx-6xx) sem atendimento dá `sit`, com ou sem tons SIT: a rede tocou o erro. O motivo diz isso, por exemplo `3.0 s of early media, then 404 Not Found`.

| Resultado | Significado |
|---|---|
| `human` | Saudação curta, depois esperou |
| `machine` | URA ou saudação gravada |
| `voicemail` | Bipe de caixa postal |
| `sit` | Anúncio da rede (ex.: número inexistente): tons SIT, ou fala em early media antes de uma falha |
| `ivr` | Um menu de URA ("digite 1"); só pelas palavras, veja abaixo |
| `silence` | Ninguém falou em 2,5 s, nem depois na chamada |
| `unsure` | Sem decisão em 5 s |

`silence` é provisório. Muitas URAs atendem mudas e falam alguns segundos depois: quando uma voz chega depois de `silence`, a camada 2 recomeça a partir dessa primeira voz, com os mesmos limites, e o resultado dela (`machine`, `human` ou `unsure`) vem como uma nova decisão. O motivo então diz isso, por exemplo `greeting longer than 2000ms after 3.0 s of silence`, e `leading_silence_ms` no relatório guarda o silêncio antes da primeira voz. Espere essa segunda decisão com `call.amd(settle=...)`, ou mantenha a chamada com `--duration`.

Os limiares partem dos padrões do Asterisk; `amd_greeting_ms` (2000) e `amd_max_words` (6) são maiores, porque saudações em português ("Alô, boa tarde, quem fala?") são mais longas que "Hello?". Calibre com gravações do seu tráfego antes de confiar no resultado. Música de espera, ruído e saudações humanas longas confundem a camada 2. Chamadas recebidas não são classificadas.

| Campo | Opção | Padrão | Significado |
|---|---|---|---|
| `amd_initial_silence_ms` | `--amd-initial-silence` | 2500 | Ninguém falou por esse tempo: `silence` |
| `amd_greeting_ms` | `--amd-greeting` | 2000 | Fala mais longa que isso: `machine` |
| `amd_after_greeting_silence_ms` | `--set` | 800 | Silêncio por esse tempo depois de um alô curto: `human` |
| `amd_total_ms` | `--set` | 5000 | Sem decisão até lá: `unsure` |
| `amd_voice_rms` | `--set` | 400 | Quadros abaixo desse nível contam como silêncio |
| `amd_max_words` | `--set` | 6 | Essa quantidade de palavras seguidas: `machine` |

```bash
simple-phone call 0800123456 --profile pbx.json --amd-initial-silence 5000   # uma URA que atende muda
```

**Conferir uma gravação.** Grave o que o outro lado envia (`--record entrada.wav`) e passe pelo AMD, offline, com os limites que quiser testar:

```bash
simple-phone amd entrada.wav
simple-phone amd entrada.wav --amd-greeting 2500 --amd-max-words 4
simple-phone amd toque.wav --answered-at 4.2   # o atendimento está em 4,2 s do arquivo
```

**Palavras (opcional).** Só pelo som não dá para separar uma URA de uma saudação de caixa postal, nem um erro gravado sem tons SIT. `call.amd(transcribe=8)` também transcreve 8 s do outro lado com o STT do telefone (por exemplo `WhisperSTT`) e corrige o veredito pelas palavras: "deixe sua mensagem" / "leave a message" é `voicemail`, "não existe" / "not in service" é `sit`, "digite 1" / "press 1" é `ivr`. Bipe, tons SIT ou anúncio em early media continuam valendo mais. Vem desligado porque STT custa CPU e alguns segundos; a transcrição fica em `amd.raw["transcript"]`. Na linha de comando, com `pip install 'simple-phone[stt]'`:

```bash
simple-phone call 1002 --profile pbx.json --amd-transcribe 6 --stt-language pt
simple-phone amd entrada.wav --amd-transcribe 6 --stt-language pt   # uma gravação, offline
```

`--stt-model` escolhe o modelo do Whisper (padrão `base`).

## Áudio no WSL

Só é preciso para `--media mic` e `--speaker`. O WSLg fornece PulseAudio, que a ALSA alcança pelo plugin `pulse`:

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
| `libasound.so.2: cannot open shared object file` | Instalar a ALSA: `sudo apt install libasound2t64` (Debian 13, Ubuntu 24.04+) ou `libasound2` |
| `REGISTER rejected: 401` ou `403` | Login, senha, domínio, política do PABX |
| `REGISTER: nothing within 30s` | Endereço, porta, UDP liberado, firewall |
| `NO MEDIA`, 488 ou 415 | Codecs em comum, política de SRTP, a oferta SDP |
| RTP nos dois sentidos, mas silêncio | Grave e ouça: os pacotes podem transportar silêncio |
| `DTMF not sent` | O outro lado não negociou `telephone-event` |
| `PJMEDIA_EAUD_NODEFDEV` | Plugins ALSA e dispositivo padrão (veja WSL) |
