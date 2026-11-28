# Desenvolvimento

*[English](development.md)*

## Requisitos

Python 3.14, uv ≥ 0.13.7, git, compilador C/C++, make, pkg-config, SWIG ≥ 4.2 e os headers da ALSA. Para TLS, também os headers do OpenSSL. O Docker é opcional e só serve para os testes contra o Asterisk.

```bash
sudo apt-get install build-essential git pkg-config swig libasound2-dev   # Ubuntu 24.04
sudo apt-get install libssl-dev                                           # para PJSIP_TLS=1
```

## Scripts

| Comando | O que faz |
|---|---|
| `bash scripts/dev.sh` | Compila o PJSIP se preciso, depois `uv sync --locked --all-extras` |
| `bash scripts/check.sh` | Ruff (lint e formatação), ty, metadados de versão, sintaxe shell, testes unitários |
| `bash scripts/test.sh` | Testes unitários (`tests/test_*.py`) |
| `bash scripts/test.sh --native` | Integração PJSUA2 em localhost (`tests/native_checks.py`) |
| `bash scripts/asterisk.sh` | Sobe o Asterisk em Docker em 127.0.0.1:5060 (`stop` remove) |
| `bash scripts/build.sh` | Gera um wheel em `dist/` |
| `.venv/bin/python scripts/check_package.py` | Confere conteúdo, metadados e o comando do wheel |
| `bash scripts/build_pjsip.sh` | Recompila o PJSIP e o wrapper SWIG (`--check` só confere) |

Os testes unitários fazem chamadas de verdade entre contas em 127.0.0.1. Nada sai da máquina.

## Testes contra o Asterisk

`tests/asterisk/` tem a configuração de um PABX pequeno: ramais 1001 e 1002 (senha `secret`), teste de eco no 600, DTMF no 601, ocupado no 602, hints para BLF e uma caixa postal para MWI.

```bash
bash scripts/asterisk.sh
ASTERISK_HOST=127.0.0.1 .venv/bin/python -m unittest discover -s tests -t tests -p 'test_asterisk.py' -v
bash scripts/asterisk.sh stop
```

O Asterisk roda na rede do host, então SIP e RTP não precisam de mapeamento de portas. `ASTERISK_IMAGE` troca a imagem, que é fixada por digest.

## Build nativo

| Variável | Padrão | Uso |
|---|---|---|
| `PJSIP_VERSION` | `2.17` | Tag a compilar |
| `PJSIP_PREFIX` | `build/pjsip` | Onde ficam as bibliotecas estáticas |
| `PJSIP_SRC` | `build/pjproject` | Checkout do PJPROJECT |
| `PJSIP_TLS` | `0` | `1` compila com OpenSSL |
| `PJSIP_JOBS` | `nproc` | Jobs paralelos do make |

Use o mesmo `PJSIP_TLS` no `dev.sh` e no `build.sh`. O `--check` compara versão, limites, TLS e o wrapper, e nunca reaproveita um prefixo que não bate.

O binding é o `pjsua2.i` do PJSIP mais o `packaging/pjsua2_extra.i`, que acrescenta o que o PJSUA2 não expõe (hoje, `setCompactForm`). Depois de mudar esse arquivo, rode `bash scripts/build_pjsip.sh` e `bash scripts/dev.sh`.

Só wheels são distribuídos. Um build a partir do fonte precisa rodar `scripts/build_pjsip.sh` antes, e um sdist comum não consegue. Gere sempre com `--wheel`; o `build.sh` já faz isso.

## Windows

Visual Studio 2022 Build Tools com o workload de C++, git, uv e SWIG (`uv tool install swig`). No PowerShell:

```powershell
pwsh scripts/build_pjsip.ps1          # PJSIP (MSBuild, Release-Dynamic) e o wrapper SWIG
uv build --wheel                      # o setup.py liga as .lib de build\pjproject
```

Pelo WSL, `bash scripts/ci-windows.sh` copia o checkout para `C:\sp\simple-phone` (`WIN_DIR`) e roda lá o `scripts\ci-windows.bat`: PJSIP, wheel, a conferência dele, os testes PJSUA2 e unitários, os mesmos passos da publicação. No Linux, o `check.sh` também confere os tipos para Windows e roda os testes do comando em cp1252, a codificação de um pipe do Windows.

`PJSIP_SRC` aponta para outro checkout do PJPROJECT, `SWIG` para outro swig.exe. O build de Windows tem só os codecs embutidos do PJSIP (sem opus) e não tem TLS.

## CI

O `.github/workflows/ci.yml` roda em pushes para `main` e em pull requests, num job só:

1. Compila o PJSIP. As bibliotecas e o wrapper SWIG ficam em cache pelo hash de `scripts/build_pjsip.sh`, `packaging/config_site.h` e `packaging/pjsua2_extra.i`.
2. Roda o `check.sh`, que cobre ruff, ty e os testes unitários, e depois os testes nativos.
3. Sobe o Asterisk com `scripts/asterisk.sh` e roda `tests/test_asterisk.py` contra ele.

Para gastar minutos do Actions só com execuções que passam:

- `bash scripts/ci.sh` roda os mesmos passos nesta máquina; `--wheel` também gera e confere o wheel. Os testes do Asterisk precisam de Docker.
- `.githooks/pre-push` roda isso antes de cada `git push`. O `scripts/dev.sh` liga o hook (`git config core.hooksPath .githooks`). Quando o push muda só texto (`*.md`, `docs/`, `examples/api/`), o hook roda só o `check.sh`. Para pular uma vez: `git push --no-verify`.
- A CI ignora pushes que mudam só texto, e um push novo cancela a execução em andamento.
- O [act](https://github.com/nektos/act) roda o próprio workflow em Docker, se você quiser os passos exatos do GitHub; ele baixa uma imagem de runner de vários GB.

## Publicação

O `.github/workflows/release.yml` roda numa tag `v*`:

1. A tag precisa ser `v` + a versão do `pyproject.toml`.
2. O cibuildwheel gera wheels `manylinux_2_28` e roda os testes unitários e nativos em cada um.
3. Os wheels são publicados no PyPI por trusted publishing, sem token guardado.

Configuração única no PyPI: cadastre um trusted publisher (Account → Publishing) com este repositório, o workflow `release.yml` e o environment `pypi`. No GitHub, crie o environment `pypi`.

Para publicar:

1. Atualize `version` no `pyproject.toml` e `__version__` em `src/simple_phone/version.py`. O `check_package.py --metadata` falha se forem diferentes.
2. Rode `uv lock`, para que o `uv sync --locked` aceite a versão nova.
   Depois, `bash scripts/ci.sh --wheel`: a publicação gera os wheels sem rodar a CI de novo.
3. Acrescente a versão ao `CHANGELOG.md` e faça o commit `chore: release X.Y.Z`.
4. Crie a tag e envie:

   ```bash
   git tag vX.Y.Z && git push origin main vX.Y.Z
   ```

O PyPI nunca aceita a mesma versão duas vezes. Para testar antes, gere localmente com `uvx cibuildwheel --platform linux` (precisa de Docker) e envie ao TestPyPI: `uv publish --publish-url https://test.pypi.org/legacy/ wheelhouse/*`.
