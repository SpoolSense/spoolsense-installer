#!/usr/bin/env bash
set -euo pipefail

# SpoolSense Installer
# Usage: curl -sL https://raw.githubusercontent.com/SpoolSense/spoolsense-installer/main/install.sh | bash

REPO_URL="https://github.com/SpoolSense/spoolsense-installer.git"
INSTALL_DIR="${HOME}/.spoolsense-installer"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║       SpoolSense Installer           ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is required but not installed."
    echo ""
    echo "Install it with:"
    echo "  Raspberry Pi / Debian: sudo apt install python3 python3-pip"
    echo "  macOS:                 brew install python3"
    exit 1
fi

# Check Python version >= 3.9
if ! python3 -c "import sys; exit(0) if sys.version_info >= (3,9) else exit(1)" 2>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "ERROR: Python 3.9 or newer is required."
    echo "  You have: Python ${PY_VER}"
    echo "  Install a newer Python or use pyenv."
    exit 1
fi

# Check git
if ! command -v git &>/dev/null; then
    echo "ERROR: git is required but not installed."
    echo ""
    echo "Install it with:"
    echo "  Raspberry Pi / Debian: sudo apt install git"
    echo "  macOS:                 xcode-select --install"
    exit 1
fi

# Clone or update the installer
if [ -d "$INSTALL_DIR" ]; then
    echo "Updating installer..."
    git -C "$INSTALL_DIR" pull --quiet
else
    echo "Downloading installer..."
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi

# Install Python dependencies into the installer's own venv — never the
# system interpreter (PEP 668 / Debian Bookworm)
VENV_DIR="$INSTALL_DIR/.venv"
if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating virtual environment..."
    if ! python3 -m venv "$VENV_DIR"; then
        echo "ERROR: could not create a virtual environment."
        echo "  Raspberry Pi / Debian: sudo apt install python3-venv"
        exit 1
    fi
fi
echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade esptool esp-idf-nvs-partition-gen

# Run the installer with the venv python so esptool/nvs-gen module
# fallbacks (python -m ...) resolve inside the venv
echo ""
"$VENV_DIR/bin/python" "$INSTALL_DIR/install.py" "$@" < /dev/tty
