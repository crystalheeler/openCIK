#!/bin/bash
# Run as root in fresh Ubuntu 22.04 WSL2 distro to bootstrap a buildozer dev env.
# Idempotent-ish: re-runnable if a step fails partway.
set -e

USER_NAME="jerrysmith"

echo "=== creating user $USER_NAME with passwordless sudo ==="
if ! id "$USER_NAME" >/dev/null 2>&1; then
    useradd -m -s /bin/bash -G sudo "$USER_NAME"
fi
echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$USER_NAME"
chmod 440 "/etc/sudoers.d/$USER_NAME"

echo "=== setting wsl.conf default user ==="
cat > /etc/wsl.conf <<EOF
[user]
default=$USER_NAME

[interop]
appendWindowsPath=true
EOF

echo "=== apt update ==="
apt-get update -qq

echo "=== apt upgrade ==="
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq

echo "=== installing Buildozer system deps ==="
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git zip unzip \
    openjdk-17-jdk \
    python3-pip python3-venv python3-setuptools \
    autoconf libtool pkg-config \
    zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 \
    cmake libffi-dev libssl-dev \
    build-essential ccache

echo ""
echo "=== versions installed ==="
python3 --version
pip3 --version | head -1
java -version 2>&1 | head -1
echo ""
echo "DONE WITH ROOT SETUP"
