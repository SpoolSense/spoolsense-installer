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

# Install Python dependencies
echo "Installing dependencies..."
pip3 install --quiet --break-system-packages esptool esp-idf-nvs-partition-gen 2>/dev/null || pip3 install --quiet esptool esp-idf-nvs-partition-gen

# Run the installer
echo ""
python3 "$INSTALL_DIR/install.py" "$@"
