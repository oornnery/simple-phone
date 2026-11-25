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

## CI

O `.github/workflows/ci.yml` roda em pushes para `main` e em pull requests:

1. **lint:** `ruff check` e `ruff format --check`.
2. **test:**
   1. Compila o PJSIP. As bibliotecas e o wrapper SWIG ficam em cache pelo hash de `scripts/build_pjsip.sh` e `packaging/config_site.h`.
   2. Roda o `check.sh`, que cobre ruff, ty e os testes unitários, e depois os testes nativos.
   3. Sobe o Asterisk com `scripts/asterisk.sh` e roda `tests/test_asterisk.py` contra ele.
   4. Gera o wheel e o confere.

## Publicação

O `.github/workflows/release.yml` roda numa tag `v*`:

1. O workflow de CI roda primeiro.
2. A tag precisa ser `v` + a versão do `pyproject.toml`.
3. O cibuildwheel gera wheels `manylinux_2_28` e roda os testes unitários e nativos em cada um.
4. Os wheels são publicados no PyPI por trusted publishing, sem token guardado.

Configuração única no PyPI: cadastre um trusted publisher (Account → Publishing) com este repositório, o workflow `release.yml` e o environment `pypi`. No GitHub, crie o environment `pypi`.

Para publicar:

1. Atualize `version` no `pyproject.toml` e `__version__` em `src/simple_phone/version.py`. O `check_package.py --metadata` falha se forem diferentes.
2. Rode `uv lock`, para que o `uv sync --locked` aceite a versão nova.
3. Acrescente a versão ao `CHANGELOG.md` e faça o commit `chore: release X.Y.Z`.
4. Crie a tag e envie:

   ```bash
   git tag vX.Y.Z && git push origin main vX.Y.Z
   ```

O PyPI nunca aceita a mesma versão duas vezes. Para testar antes, gere localmente com `uvx cibuildwheel --platform linux` (precisa de Docker) e envie ao TestPyPI: `uv publish --publish-url https://test.pypi.org/legacy/ wheelhouse/*`.
