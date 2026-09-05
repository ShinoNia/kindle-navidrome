#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION="${OPENSSL_VERSION:-1.1.1}"
TARGET="${TARGET:-arm-linux-gnueabihf}"

SYSROOT="${ROOT}/build/sysroot"
OUT="${ROOT}/build/rootfs"

PREFIX="/opt/openssl-${VERSION}"

JOBS="${JOBS:-$(nproc)}"

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

# ============================================================
# IMPORTANT
#
# OpenSSL 1.1.1 uses CROSS_COMPILE internally.
# Do not provide CC=arm-linux-gnueabihf-gcc at the same time.
# ============================================================

unset CROSS_COMPILE
unset CC
unset CXX
unset AR
unset RANLIB
unset STRIP

export SYSROOT

export CFLAGS="--sysroot=${SYSROOT}"
export CXXFLAGS="--sysroot=${SYSROOT}"
export LDFLAGS="--sysroot=${SYSROOT}"

# ============================================================
# CONFIGURE
# ============================================================

./Configure \
    linux-armv4 \
    shared \
    no-tests \
    --cross-compile-prefix="${TARGET}-" \
    --prefix="${PREFIX}" \
    --openssldir="${PREFIX}"

# ============================================================
# SHOW COMPILER
# ============================================================

echo
echo "Compiler from generated Makefile:"
grep -E '^(CC|CROSS_COMPILE)[[:space:]]*=' Makefile || true

echo
echo "Expected compiler:"
echo "${TARGET}-gcc"

# ============================================================
# BUILD
# ============================================================

make -j"${JOBS}"

# ============================================================
# INSTALL
# ============================================================

make DESTDIR="${OUT}" install_sw

# ============================================================
# VERIFY
# ============================================================

echo
echo "=========================================="
echo "OpenSSL artifacts"
echo "=========================================="

file "${OUT}${PREFIX}/bin/openssl"

file "${OUT}${PREFIX}/lib/libssl.so.1.1"

file "${OUT}${PREFIX}/lib/libcrypto.so.1.1"

echo
echo "OpenSSL build complete."

cd /

rm -rf \
    "/tmp/openssl-${VERSION}" \
    "/tmp/openssl-${VERSION}.tar.gz"
