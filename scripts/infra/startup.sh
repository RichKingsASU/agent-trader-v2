#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

echo "🔹 Starting automated setup..."

# 1. Install KVM & Virtualization Tools (Silent Mode)
apt-get update
apt-get install -y -o Dpkg::Options::="--force-confold" \
    qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils curl

# 2. Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# 3. Install Firecracker (Latest)
LATEST_RELEASE_URL="https://api.github.com/repos/firecracker-microvm/firecracker/releases/latest"
LATEST_VERSION=$(curl -s ${LATEST_RELEASE_URL} | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
ARCH=$(uname -m)
DOWNLOAD_URL="https://github.com/firecracker-microvm/firecracker/releases/download/${LATEST_VERSION}/firecracker-${LATEST_VERSION}-${ARCH}"

echo "🔹 Downloading Firecracker version ${LATEST_VERSION}..."
curl -L -o /usr/local/bin/firecracker ${DOWNLOAD_URL}
chmod +x /usr/local/bin/firecracker

# 4. Global Permissions (Optional but helpful)
# Allow anyone in the 'docker' group to run containers
chmod 666 /var/run/docker.sock || true

echo "✅ Sandbox Host setup complete."
