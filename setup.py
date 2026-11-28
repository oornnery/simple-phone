"""Builds the PJSUA2 extension from the wrapper made by scripts/build_pjsip.sh."""

import os
import shlex
import subprocess
import sys
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


def unix_build():
    return {
        # A native rebuild must invalidate the Python extension, even if SWIG's
        # generated C++ didn't change (TLS policy, limits or static libraries).
        "depends": [
            str(p)
            for p in [
                PREFIX / "include/pj/config_site.h",
                PREFIX / "lib/pkgconfig/libpjproject.pc",
                *sorted((PREFIX / "lib").glob("*.a")),
            ]
        ],
        "extra_compile_args": pkg_config("--cflags") + ["-O2"],
        "extra_link_args": link_args(),
    }


def windows_build():
    """MSBuild leaves PJSIP in its source tree (PJSIP_SRC): headers and the
    Release-Dynamic (/MD, like Python) libraries, no pkg-config."""
    src = Path(os.environ.get("PJSIP_SRC", ROOT / "build" / "pjproject")).resolve()
    tag = "x86_64-x64-vc14-Release-Dynamic"
    libraries = [
        src / "lib" / f"libpjproject-{tag}.lib",
        src / "pjsip" / "lib" / f"pjsua2-lib-{tag}.lib",
    ]
    return {
        "include_dirs": [
            str(src / name / "include")
            for name in ("pjlib", "pjlib-util", "pjmedia", "pjsip", "pjnath")
        ],
        "depends": [str(src / "pjlib/include/pj/config_site.h"), *map(str, libraries)],
        "extra_objects": [str(lib) for lib in libraries],
        "libraries": [
            "ws2_32",
            "iphlpapi",
            "winmm",
            "ole32",
            "oleaut32",
            "uuid",
            "advapi32",
            "user32",
            "mswsock",
            "dsound",
            "netapi32",
        ],  # fmt: skip
        "extra_compile_args": ["/O2", "/EHsc", "/bigobj"],
    }


setup(
    ext_modules=[
        Extension(
            "simple_phone._native._pjsua2",
            sources=[str(WRAPPER)],
            **(windows_build() if sys.platform == "win32" else unix_build()),
        )
    ]
)
