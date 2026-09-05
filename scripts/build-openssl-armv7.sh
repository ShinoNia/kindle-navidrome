#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VERSION="${OPENSSL_VERSION:-1.1.1}"
TARGET="${TARGET:-arm-linux-gnueabihf}"

SYSROOT="${ROOT}/build/sysroot"
OUT="${ROOT}/build/rootfs"

PREFIX="/opt/openssl-${VERSION}"

JOBS="${JOBS:-$(nproc)}"

echo "=========================================="
echo "OpenSSL ${VERSION}"
echo "Target: ${TARGET}"
echo "Sysroot: ${SYSROOT}"
echo "Jobs:   ${JOBS}"
echo "=========================================="

# ------------------------------------------------------------
# Verify toolchain
# ------------------------------------------------------------

command -v "${TARGET}-gcc"
command -v "${TARGET}-ar"
command -v "${TARGET}-ranlib"

echo
echo "Compiler:"
"${TARGET}-gcc" --version | head -1

echo
echo "Sysroot:"
test -d "${SYSROOT}"

# ------------------------------------------------------------
# Clean
# ------------------------------------------------------------

cd /tmp

rm -rf \
    "openssl-${VERSION}" \
    "openssl-${VERSION}.tar.gz"

# ------------------------------------------------------------
# Download
# ------------------------------------------------------------

wget \
    "https://www.openssl.org/source/openssl-${VERSION}.tar.gz"

tar -xzf "openssl-${VERSION}.tar.gz"

cd "openssl-${VERSION}"

# ------------------------------------------------------------
# IMPORTANT
#
# Do NOT set CC to ${TARGET}-gcc here.
#
# OpenSSL does:
#
#   CC = CROSS_COMPILE + CC
#
# Therefore:
#
#   CROSS_COMPILE=arm-linux-gnueabihf-
#   CC=gcc
#
# becomes:
#
#   arm-linux-gnueabihf-gcc
#
# ------------------------------------------------------------

unset CROSS_COMPILE
unset CC
unset CXX
unset AR
unset RANLIB
unset LD

# ------------------------------------------------------------
# Cross compile flags
# ------------------------------------------------------------

export CFLAGS="--sysroot=${SYSROOT}"
export CXXFLAGS="--sysroot=${SYSROOT}"
export LDFLAGS="--sysroot=${SYSROOT}"

# ------------------------------------------------------------
# Configure
# ------------------------------------------------------------

./Configure \
    linux-armv4 \
    shared \
    no-tests \
    CC=gcc \
    AR=ar \
    RANLIB=ranlib \
    --cross-compile-prefix="${TARGET}-" \
    --prefix="${PREFIX}" \
    --openssldir="${PREFIX}"

# ------------------------------------------------------------
# Verify generated Makefile
# ------------------------------------------------------------

echo
echo "=========================================="
echo "Generated compiler configuration"
echo "=========================================="

grep -E '^(CROSS_COMPILE|CC|AR|RANLIB)[[:space:]]*=' Makefile || true

echo
echo "Expected:"
echo "  CROSS_COMPILE = ${TARGET}-"
echo "  CC            = ${TARGET}-gcc"
echo "  AR            = ${TARGET}-ar"
echo "  RANLIB        = ${TARGET}-ranlib"

# Fail immediately if OpenSSL generated the bad doubled compiler.

if grep -q "${TARGET}-${TARGET}-gcc" Makefile; then
    echo
    echo "ERROR: OpenSSL generated a doubled cross compiler:"
    grep "${TARGET}-${TARGET}-gcc" Makefile
    exit 1
fi

# ------------------------------------------------------------
# Build
# ------------------------------------------------------------

echo
echo "=========================================="
echo "Building OpenSSL"
echo "=========================================="

make -j"${JOBS}"

# ------------------------------------------------------------
# Install into target rootfs
# ------------------------------------------------------------

echo
echo "=========================================="
echo "Installing OpenSSL"
echo "=========================================="

rm -rf "${OUT}${PREFIX}"

make \
    DESTDIR="${OUT}" \
    install_sw

# ------------------------------------------------------------
# Verify ARM binaries/libraries
# ------------------------------------------------------------

echo
echo "=========================================="
echo "Verifying ARMv7 output"
echo "=========================================="

file \
    "${OUT}${PREFIX}/lib/libssl.so.1.1" \
    "${OUT}${PREFIX}/lib/libcrypto.so.1.1"

echo
echo "OpenSSL cross-build complete."

# ------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------

cd /

rm -rf \
    "/tmp/openssl-${VERSION}" \
    "/tmp/openssl-${VERSION}.tar.gz"
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
