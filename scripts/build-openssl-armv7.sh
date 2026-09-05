#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION="${OPENSSL_VERSION:-1.1.1}"
TARGET="${TARGET:-arm-linux-gnueabihf}"
SYSROOT="${ROOT}/build/sysroot"
OUT="${ROOT}/build/rootfs"

JOBS="$(nproc)"

PREFIX="/opt/openssl-${VERSION}"

mkdir -p "${OUT}"

cd /tmp

rm -rf \
    "openssl-${VERSION}" \
    "openssl-${VERSION}.tar.gz"

echo "=========================================="
echo "OpenSSL ${VERSION}"
echo "Target: ${TARGET}"
echo "Jobs:   ${JOBS}"
echo "=========================================="

wget \
    "https://www.openssl.org/source/openssl-${VERSION}.tar.gz"

tar -xzf "openssl-${VERSION}.tar.gz"

cd "openssl-${VERSION}"

export CROSS_COMPILE="${TARGET}-"

export SYSROOT

export CC="${TARGET}-gcc"
export CXX="${TARGET}-g++"
export AR="${TARGET}-ar"
export RANLIB="${TARGET}-ranlib"
export STRIP="${TARGET}-strip"

export CFLAGS="--sysroot=${SYSROOT}"
export CXXFLAGS="--sysroot=${SYSROOT}"
export LDFLAGS="--sysroot=${SYSROOT}"

./Configure \
    linux-armv4 \
    shared \
    no-tests \
    --cross-compile-prefix="${TARGET}-" \
    --prefix="${PREFIX}" \
    --openssldir="${PREFIX}"

make -j"${JOBS}"

make DESTDIR="${OUT}" install_sw

cd /

rm -rf \
    "/tmp/openssl-${VERSION}" \
    "/tmp/openssl-${VERSION}.tar.gz"

echo
echo "OpenSSL result:"
file "${OUT}${PREFIX}/bin/openssl"
file "${OUT}${PREFIX}/lib/libssl.so.1.1"
file "${OUT}${PREFIX}/lib/libcrypto.so.1.1"
