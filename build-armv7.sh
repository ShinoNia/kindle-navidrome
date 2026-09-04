#!/bin/bash

set -e


# ============================================================
# ENVIRONMENT
# ============================================================

export DEBIAN_FRONTEND=noninteractive

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


echo
echo "========================================"
echo "ARMv7 Ubuntu 14.04 BUILD"
echo "========================================"

echo
echo "Kernel architecture:"
uname -m

echo
echo "Debian architecture:"
dpkg --print-architecture


# ============================================================
# UBUNTU 14.04 REPOSITORIES
# ============================================================

echo
echo "========================================"
echo "APT"
echo "========================================"

sed -i \
    's|http://archive.ubuntu.com/ubuntu|http://old-releases.ubuntu.com/ubuntu|g' \
    /etc/apt/sources.list

sed -i \
    's|http://security.ubuntu.com/ubuntu|http://old-releases.ubuntu.com/ubuntu|g' \
    /etc/apt/sources.list

apt-get update


# ============================================================
# SYSTEM DEPENDENCIES
# ============================================================

echo
echo "========================================"
echo "SYSTEM DEPENDENCIES"
echo "========================================"

apt-get install -y \
    build-essential \
    ca-certificates \
    curl \
    wget \
    git \
    make \
    gcc \
    g++ \
    patch \
    pkg-config \
    zlib1g \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncurses5-dev \
    libncursesw5-dev \
    libffi-dev \
    liblzma-dev \
    tk-dev \
    libx11-6 \
    libx11-dev \
    libxext6 \
    libxext-dev \
    libxrender1 \
    libxrender-dev \
    libxft2 \
    libxft-dev \
    libjpeg-dev \
    libpng12-dev \
    libfreetype6-dev \
    libflac-dev \
    libflac8 \
    file \
    binutils


# ============================================================
# VERIFY LIBFLAC
# ============================================================

echo
echo "========================================"
echo "LIBFLAC"
echo "========================================"

ldconfig -p | grep flac || true

dpkg -l | grep libflac || true


# ============================================================
# BUILD OPENSSL 1.0.2u
#
# Ubuntu 14.04 has an old OpenSSL version.
# Python 3.7.5 needs a newer compatible OpenSSL.
# ============================================================

echo
echo "========================================"
echo "OPENSSL 1.0.2u"
echo "========================================"

cd /tmp

rm -rf openssl-1.0.2u
rm -f openssl-1.0.2u.tar.gz

wget \
    https://www.openssl.org/source/openssl-1.0.2u.tar.gz

tar \
    -xzf \
    openssl-1.0.2u.tar.gz

cd openssl-1.0.2u


./config \
    --prefix=/opt/openssl-1.0.2u \
    --openssldir=/opt/openssl-1.0.2u \
    shared \
    zlib


make -j2

make install


# ============================================================
# OPENSSL ENVIRONMENT
# ============================================================

export OPENSSL_ROOT="/opt/openssl-1.0.2u"

export CPPFLAGS="-I${OPENSSL_ROOT}/include"

export CFLAGS="-I${OPENSSL_ROOT}/include"

export LDFLAGS="-L${OPENSSL_ROOT}/lib -Wl,-rpath,${OPENSSL_ROOT}/lib"

export LD_LIBRARY_PATH="${OPENSSL_ROOT}/lib"

export LD_RUN_PATH="${OPENSSL_ROOT}/lib"


echo
echo "OpenSSL version:"

${OPENSSL_ROOT}/bin/openssl version


# ============================================================
# BUILD PYTHON 3.7.5
# ============================================================

echo
echo "========================================"
echo "PYTHON 3.7.5"
echo "========================================"

cd /tmp

rm -rf Python-3.7.5
rm -f Python-3.7.5.tgz

wget \
    https://www.python.org/ftp/python/3.7.5/Python-3.7.5.tgz


tar \
    -xzf \
    Python-3.7.5.tgz


cd Python-3.7.5


./configure \
    --prefix=/opt/python-3.7.5 \
    --with-openssl="${OPENSSL_ROOT}"


make -j2

make install


# ============================================================
# PYTHON
# ============================================================

export PYTHON="/opt/python-3.7.5/bin/python3"

export PIP="${PYTHON} -m pip"


echo
echo "========================================"
echo "PYTHON VERIFICATION"
echo "========================================"


echo
echo "Python version:"

${PYTHON} --version


echo
echo "Python machine:"

${PYTHON} -c \
    "import platform; print(platform.machine())"


echo
echo "Python architecture:"

${PYTHON} -c \
    "import struct; print(str(struct.calcsize('P') * 8) + '-bit')"


echo
echo "zlib:"

${PYTHON} -c \
    "import zlib; print(zlib.ZLIB_VERSION)"


echo
echo "SSL:"

${PYTHON} -c \
    "import ssl; print(ssl.OPENSSL_VERSION)"


echo
echo "Tkinter:"

${PYTHON} -c \
    "import tkinter; print(tkinter.TkVersion)"


# ============================================================
# ENSUREPIP
# ============================================================

echo
echo "========================================"
echo "PIP"
echo "========================================"


${PYTHON} -m ensurepip


${PYTHON} -m pip install \
    --upgrade \
    "pip<24" \
    "setuptools<70" \
    wheel


# ============================================================
# APPLICATION DEPENDENCIES
# ============================================================

echo
echo "========================================"
echo "APPLICATION DEPENDENCIES"
echo "========================================"


if [ -f requirements.txt ]; then

    ${PYTHON} -m pip install \
        -r requirements.txt

fi


# ============================================================
# EXPLICIT DEPENDENCIES
# ============================================================

${PYTHON} -m pip install \
    requests \
    Pillow \
    pyflac


# ============================================================
# VERIFY PYTHON MODULES
# ============================================================

echo
echo "========================================"
echo "MODULE VERIFICATION"
echo "========================================"


${PYTHON} -c \
    "import requests; print('requests OK')"


${PYTHON} -c \
    "from PIL import Image, ImageTk; print('Pillow OK')"


${PYTHON} -c \
    "import pyflac; print('pyflac OK')"


${PYTHON} -c \
    "import tkinter; from tkinter import messagebox; print('Tkinter OK')"


# ============================================================
# PYINSTALLER
# ============================================================

echo
echo "========================================"
echo "PYINSTALLER"
echo "========================================"


${PYTHON} -m pip install \
    pyinstaller


echo
echo "PyInstaller version:"

${PYTHON} -m PyInstaller \
    --version


# ============================================================
# CLEAN PREVIOUS BUILD
# ============================================================

echo
echo "========================================"
echo "CLEAN"
echo "========================================"


rm -rf build
rm -rf dist


# ============================================================
# BUILD APPLICATION
# ============================================================

echo
echo "========================================"
echo "PYINSTALLER BUILD"
echo "========================================"


${PYTHON} -m PyInstaller \
    --clean \
    --onefile \
    --name kindle-navidrome \
    app.py


# ============================================================
# VERIFY OUTPUT
# ============================================================

echo
echo "========================================"
echo "BUILD RESULT"
echo "========================================"


ls -lah dist/


echo
echo "File type:"

file \
    dist/kindle-navidrome


echo
echo "ELF architecture:"

readelf \
    -h \
    dist/kindle-navidrome \
    | grep -E 'Class|Machine'


echo
echo "Dynamic dependencies:"

readelf \
    -d \
    dist/kindle-navidrome \
    | grep NEEDED || true


echo
echo "========================================"
echo "BUILD COMPLETE"
echo "========================================"
