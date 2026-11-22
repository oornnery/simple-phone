#!/usr/bin/env bash
# Static PIC PJSIP + Python-independent SWIG wrapper.
# PJSIP_VERSION=2.17; PJSIP_TLS=0|1; PJSIP_JOBS=<parallel make jobs>
# PJSIP_PREFIX=<repo>/build/pjsip; PJSIP_SRC=<repo>/build/pjproject
# --check only validates existing outputs; it never downloads or compiles.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${PJSIP_VERSION:-2.17}"
PREFIX="${PJSIP_PREFIX:-$ROOT/build/pjsip}"
SRC="${PJSIP_SRC:-$ROOT/build/pjproject}"
OUT="$ROOT/src/simple_phone/_native"
PREFIX="$(realpath -m "$PREFIX")"
SRC="$(realpath -m "$SRC")"
TLS="${PJSIP_TLS:-0}"
case "$TLS" in 0|1) ;; *) echo "PJSIP_TLS must be 0 or 1" >&2; exit 2 ;; esac
case "${1:-}" in
    ""|--check) ;;
    *) echo "Usage: bash scripts/build_pjsip.sh [--check]" >&2; exit 2 ;;
esac

check_outputs() {
    for file in "$OUT/pjsua2.py" "$OUT/pjsua2_wrap.cpp" "$OUT/_build.py" \
        "$PREFIX/lib/pkgconfig/libpjproject.pc" "$PREFIX/include/pj/config_site.h" \
        "$PREFIX/include/pj/compat/os_auto.h"; do
        [[ -f "$file" ]] || { echo "Native build missing: $file" >&2; return 1; }
    done
    grep -Fq "PJSIP_VERSION = \"$VERSION\"" "$OUT/_build.py" || {
        echo "Native wrapper version differs from PJSIP_VERSION=$VERSION" >&2; return 1;
    }
    grep -Eq "^Version: ${VERSION//./\\.}$" "$PREFIX/lib/pkgconfig/libpjproject.pc" || return 1
    cmp -s "$ROOT/packaging/config_site.h" "$PREFIX/include/pj/config_site.h" || {
        echo "Native limits differ from packaging/config_site.h" >&2; return 1;
    }
    local compiled_tls=0
    if grep -Eq '^#define PJ_HAS_SSL_SOCK[[:space:]]+1' "$PREFIX/include/pj/compat/os_auto.h"; then
        compiled_tls=1
    fi
    [[ "$compiled_tls" == "$TLS" ]] || {
        echo "Native TLS configuration differs from PJSIP_TLS=$TLS" >&2; return 1;
    }
    compgen -G "$PREFIX/lib/libpjsua2*.a" >/dev/null || return 1
}

if [[ "${1:-}" == --check ]]; then
    check_outputs
    exit
fi
for tool in git make pkg-config swig "${CC:-cc}" "${CXX:-c++}"; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done
swig_version="$(swig -version | awk '/SWIG Version/{print $3}')"
IFS=. read -r swig_major swig_minor _ <<< "$swig_version"
if (( swig_major < 4 || (swig_major == 4 && swig_minor < 2) )); then
    echo "SWIG >= 4.2 required; found $swig_version" >&2
    exit 1
fi
pkg-config --exists alsa || { echo "Install the ALSA development headers first." >&2; exit 1; }
SSL_ARGS=(--disable-ssl)
if [[ "$TLS" == 1 ]]; then
    pkg-config --exists openssl || { echo "TLS needs OpenSSL development headers." >&2; exit 1; }
    SSL_ARGS=()
fi
JOBS="${PJSIP_JOBS:-$(nproc)}"
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || { echo "PJSIP_JOBS must be positive." >&2; exit 2; }
mkdir -p "$OUT" "$(dirname "$SRC")" "$PREFIX"
if [[ ! -d "$SRC" ]]; then
    git clone --depth 1 --branch "$VERSION" https://github.com/pjsip/pjproject.git "$SRC"
fi
[[ -f "$SRC/configure" ]] || { echo "PJSIP_SRC is not a PJPROJECT checkout: $SRC" >&2; exit 1; }
source_part() {
    sed -n "s/^export PJ_VERSION_$1[[:space:]]*:=[[:space:]]*//p" "$SRC/version.mak"
}
source_version="$(source_part MAJOR).$(source_part MINOR)"
revision="$(source_part REV)"
[[ -z "$revision" ]] || source_version+=".$revision"
source_version+="$(source_part SUFFIX)"
[[ "$source_version" == "$VERSION" ]] || {
    echo "PJSIP_SRC contains $source_version, but PJSIP_VERSION requests $VERSION" >&2
    exit 1
}
# Reconfiguration changes (TLS/limits/compiler flags) must not reuse old objects.
if [[ -f "$SRC/build.mak" ]]; then
    make -C "$SRC" distclean
fi
cp "$ROOT/packaging/config_site.h" "$SRC/pjlib/include/pj/config_site.h"
cd "$SRC"
./configure --prefix="$PREFIX" --disable-video "${SSL_ARGS[@]}" \
    CFLAGS="-O2 -fPIC -DNDEBUG" CXXFLAGS="-O2 -fPIC -DNDEBUG"
make dep
make -j"$JOBS"
make install
swig -c++ -python -threads -doxygen -w312 \
    -I"$SRC/pjlib/include" -I"$SRC/pjlib-util/include" \
    -I"$SRC/pjmedia/include" -I"$SRC/pjsip/include" -I"$SRC/pjnath/include" \
    -outdir "$OUT" -o "$OUT/pjsua2_wrap.cpp" "$SRC/pjsip-apps/src/swig/pjsua2.i"
build_id="$(sha256sum "$PREFIX"/lib/*.a | sha256sum | awk '{print $1}')"
printf 'PJSIP_VERSION = "%s"\nPJSIP_TLS = %s\nPJSIP_BUILD_ID = "%s"\n' \
    "$VERSION" "$TLS" "$build_id" > "$OUT/_build.py"
check_outputs
echo "PJSIP $VERSION (TLS=$TLS) installed in $PREFIX; wrapper generated in $OUT"
