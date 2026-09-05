#!/usr/bin/env bash

set -euo pipefail

ROOT="$(pwd)/cross"

OPENSSL_VERSION="1.1.1"
PYTHON_VERSION="3.7.5"

PREFIX="${ROOT}/opt"

SYSROOT="/usr/arm-linux-gnueabihf"

CC="arm-linux-gnueabihf-gcc"
CXX="arm-linux-gnueabihf-g++"
AR="arm-linux-gnueabihf-ar"
RANLIB="arm-linux-gnueabihf-ranlib"
STRIP="arm-linux-gnueabihf-strip"

mkdir -p "${ROOT}"
mkdir -p "${PREFIX}"

export PATH="/usr/bin:${PATH}"

export CC
export CXX
export AR
export RANLIB
export STRIP

export PKG_CONFIG_SYSROOT_DIR="${SYSROOT}"
export PKG_CONFIG_LIBDIR="${SYSROOT}/usr/lib/arm-linux-gnueabihf/pkgconfig:${SYSROOT}/usr/lib/pkgconfig"

export CPPFLAGS="--sysroot=${SYSROOT}"
export CFLAGS="--sysroot=${SYSROOT}"
export CXXFLAGS="--sysroot=${SYSROOT}"
export LDFLAGS="--sysroot=${SYSROOT}"

cd "${ROOT}"

# ============================================================
# OpenSSL
# ============================================================

if [ ! -d "${PREFIX}/openssl-${OPENSSL_VERSION}" ]; then

    wget -q \
      "https://www.openssl.org/source/openssl-${OPENSSL_VERSION}.tar.gz"

    tar xf "openssl-${OPENSSL_VERSION}.tar.gz"

    cd "openssl-${OPENSSL_VERSION}"

    ./Configure \
        linux-generic32 \
        shared \
        no-tests \
        --cross-compile-prefix=arm-linux-gnueabihf- \
        --prefix="${PREFIX}/openssl-${OPENSSL_VERSION}" \
        --openssldir="${PREFIX}/openssl-${OPENSSL_VERSION}"

    make -j"$(nproc)"

    make install_sw

    cd "${ROOT}"

    rm -rf \
        "openssl-${OPENSSL_VERSION}" \
        "openssl-${OPENSSL_VERSION}.tar.gz"
fi


# ============================================================
# Python
# ============================================================

if [ ! -d "${PREFIX}/python-${PYTHON_VERSION}" ]; then

    wget -q \
      "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz"

    tar xf "Python-${PYTHON_VERSION}.tgz"

    cd "Python-${PYTHON_VERSION}"

    # --------------------------------------------------------
    # Python needs a native interpreter for build-time tools.
    #
    # This is supplied by the GitHub Ubuntu runner.
    # --------------------------------------------------------

    ./configure \
        --host=arm-linux-gnueabihf \
        --build=x86_64-linux-gnu \
        --prefix="/opt/python-${PYTHON_VERSION}" \
        --with-openssl="${PREFIX}/openssl-${OPENSSL_VERSION}" \
        --enable-shared \
        ac_cv_file__dev_ptmx=yes \
        ac_cv_file__dev_ptc=no

    make -j"$(nproc)"

    # Do not run the ARM Python.
    #
    # INSTALL commands which invoke Python need special handling.
    # For the first pass, install the generated tree directly.

    DESTDIR="${ROOT}" make install

    cd "${ROOT}"

    rm -rf \
        "Python-${PYTHON_VERSION}" \
        "Python-${PYTHON_VERSION}.tgz"
fi


echo
echo "========================================"
echo "Cross compilation complete"
echo "========================================"
echo

file "${PREFIX}/python-${PYTHON_VERSION}/bin/python3" || true

echo
echo "ARMv7 files:"
find "${PREFIX}" -maxdepth 3 -type f | head -50
