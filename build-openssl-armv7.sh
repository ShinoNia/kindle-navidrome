#!/usr/bin/env bash

set -euo pipefail

VERSION="1.1.1"
PREFIX="$(pwd)/openssl-armv7"

JOBS="$(nproc)"

echo "========================================"
echo "Building OpenSSL ${VERSION}"
echo "Target: ARMv7 hard-float"
echo "Jobs: ${JOBS}"
echo "========================================"

rm -rf "${PREFIX}"
mkdir -p "${PREFIX}"

cd /tmp

rm -rf "openssl-${VERSION}" "openssl-${VERSION}.tar.gz"

wget \
  "https://www.openssl.org/source/openssl-${VERSION}.tar.gz"

tar -xzf "openssl-${VERSION}.tar.gz"

cd "openssl-${VERSION}"

./Configure \
    linux-armv4 \
    shared \
    no-tests \
    --cross-compile-prefix=arm-linux-gnueabihf- \
    --prefix="${PREFIX}" \
    --openssldir="${PREFIX}"

make -j"${JOBS}"

make install_sw

echo
echo "========================================"
echo "OpenSSL build complete"
echo "========================================"

file "${PREFIX}/bin/openssl" || true
file "${PREFIX}/lib/libssl.so.1.1" || true
file "${PREFIX}/lib/libcrypto.so.1.1" || true

echo
echo "Installed:"
find "${PREFIX}" -maxdepth 3 -type f | sort

rm -rf \
  "/tmp/openssl-${VERSION}" \
  "/tmp/openssl-${VERSION}.tar.gz"
