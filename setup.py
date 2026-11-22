"""Builds the PJSUA2 extension from the wrapper made by scripts/build_pjsip.sh."""

import os
import shlex
import subprocess
from pathlib import Path

from setuptools import Extension, setup

ROOT = Path(__file__).parent
PREFIX = Path(os.environ.get("PJSIP_PREFIX", ROOT / "build" / "pjsip")).resolve()
WRAPPER = Path("src/simple_phone/_native/pjsua2_wrap.cpp")

if not (ROOT / WRAPPER).is_file():
    raise SystemExit(
        "Run scripts/build_pjsip.sh first: it builds PJSIP and "
        "generates the SWIG wrapper."
    )


def pkg_config(option):
    env = dict(os.environ, PKG_CONFIG_PATH=str(PREFIX / "lib" / "pkgconfig"))
    output = subprocess.check_output(
        ["pkg-config", option, "--static", "libpjproject"], env=env, text=True
    )
    return shlex.split(output)


def link_args():
    """Name our static libraries by full path. A bare -lpjsua2 could pick up
    another PJSIP from /usr/lib or /usr/local/lib that was not built as PIC."""
    args = []
    for arg in pkg_config("--libs"):
        archive = PREFIX / "lib" / f"lib{arg[2:]}.a"
        args.append(str(archive) if arg.startswith("-l") and archive.is_file() else arg)
    return args + ["-Wl,--strip-all"]


setup(
    ext_modules=[
        Extension(
            "simple_phone._native._pjsua2",
            sources=[str(WRAPPER)],
            # A native rebuild must invalidate the Python extension, even if SWIG's
            # generated C++ didn't change (TLS policy, limits or static libraries).
            depends=[
                str(p)
                for p in [
                    PREFIX / "include/pj/config_site.h",
                    PREFIX / "lib/pkgconfig/libpjproject.pc",
                    *sorted((PREFIX / "lib").glob("*.a")),
                ]
            ],
            extra_compile_args=pkg_config("--cflags") + ["-O2"],
            extra_link_args=link_args(),
        )
    ]
)
