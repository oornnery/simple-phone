"""Mídia: o que a chamada envia (fontes) e para onde vai o que ela recebe
(destinos), áudio ao vivo em Python, métricas RTP e os três tipos de DTMF.

Fontes: Silence(), Echo(), Microphone(), WavFile(path, loop=).
Destinos: Speaker(), Recorder(path). Com placa de som, troque o Recorder
por Speaker() e o WavFile por Microphone() para falar de verdade.
"""

import array
import asyncio

import local

from simple_phone import AsyncPhone, Call
from simple_phone.media import AudioFrame, Recorder, Silence, WavFile, rms


async def main():
    beep = local.write_wav("beep.wav", local.tone(880, 0.3))
    music = local.write_wav("tone.wav", local.tone(440, 1.0))
    received = local.FOLDER / "recebido.wav"

    async with AsyncPhone(local.settings()) as phone:
        far = await local.far_end(phone)

        @far.on(AsyncPhone.Incoming)
        async def answer(event):
            await event.call.answer(media="echo")  # devolve o que ouvir

        @far.on(Call.Dtmf)
        def digit(event):
            print("[outro lado] DTMF", event.digit, f"({event.method})")

        async with phone.call(far.uri) as call:
            await call.send(WavFile(music, loop=True))  # o que transmitimos
            await call.receive(Recorder(str(received)))  # o que ouvimos

            frames = []
            async for frame in call.audio():  # PCM recebido, 20 ms por quadro
                frames.append(frame)
                if len(frames) == 50:
                    break
            loudest = max(rms(f.pcm) for f in frames)
            print(f"Áudio ao vivo: {len(frames)} quadros, RMS máximo {loudest:.0f}")

            async for stats in call.stats():  # a cada stats_interval (1 s)
                print(
                    f"RTP: {stats.codec}, {stats.rx_packets} pacotes, perda"
                    f" {stats.rx_loss_percent:.1f}%, jitter {stats.jitter_ms} ms,"
                    f" buffer {stats.jitter_buffer_ms} ms, MOS {stats.mos}"
                )
                break

            await call.send(Silence())
            await call.play(beep)  # toca por cima e volta quando acaba
            stream = await call.stream()  # fonte alimentada pelo Python
            pcm = array.array("h", local.tone(660, 0.3)).tobytes()
            stream.write(AudioFrame(pcm))
            await stream.drain()

            await call.gain(microphone=0.5, speaker=1.0)
            await call.mute()
            await call.mute(False)

            await call.dtmf("1", method="rfc4733")  # eventos RTP (padrão)
            await call.dtmf("2", method="info")  # SIP INFO
            await call.dtmf("3", method="inband")  # tons no áudio (PJSUA não detecta)
            await asyncio.sleep(1)
            await call.receive()  # para de gravar

        print("Gravado:", received)


asyncio.run(main())
