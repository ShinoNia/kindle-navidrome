#!/bin/bash

set -e

export DEBIAN_FRONTEND=noninteractive

PYTHON="/opt/python-3.7.5/bin/python3"

echo
echo "========================================"
echo "ARMv7 APPLICATION BUILD"
echo "========================================"

echo
echo "Kernel architecture:"
uname -m

echo
echo "Debian architecture:"
dpkg --print-architecture

echo
echo "Python:"
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
echo "OpenSSL:"
${PYTHON} -c \
    "import ssl; print(ssl.OPENSSL_VERSION)"


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

${PYTHON} -m PyInstaller \
    --version


# ============================================================
# CLEAN
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
    app2.py


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
