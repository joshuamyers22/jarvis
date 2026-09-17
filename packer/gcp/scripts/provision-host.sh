#!/usr/bin/env bash
set -euo pipefail

required=(
  BUILDX_VERSION
  COMPOSE_VERSION
  CONTAINERD_VERSION
  DOCKER_CLI_VERSION
  DOCKER_ENGINE_VERSION
  DOCKER_REPO_KEY_SHA256
  GIT_REVISION
  IMAGE_NAME
  OPS_AGENT_INSTALLER_SHA256
  OPS_AGENT_VERSION
  RSYNC_VERSION
  SOURCE_IMAGE
)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || {
    echo "missing required image-build value: $name" >&2
    exit 1
  }
done

export DEBIAN_FRONTEND=noninteractive
source /etc/os-release
[[ "${ID:-}" == "debian" && "${VERSION_ID:-}" == "12" ]] || {
  echo "Jarvis host images must be built from Debian 12" >&2
  exit 1
}

apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  "rsync=${RSYNC_VERSION}"
apt-mark hold rsync

install -d -m 0755 /etc/apt/keyrings
docker_repo_key=$(mktemp)
curl --fail --location --proto '=https' --tlsv1.2 \
  --output "$docker_repo_key" \
  https://download.docker.com/linux/debian/gpg
printf '%s  %s\n' "$DOCKER_REPO_KEY_SHA256" "$docker_repo_key" | sha256sum --check --strict
install -m 0644 "$docker_repo_key" /etc/apt/keyrings/docker.asc
rm -f "$docker_repo_key"
architecture=$(dpkg --print-architecture)
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian %s stable\n' \
  "$architecture" "$VERSION_CODENAME" >/etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y --no-install-recommends \
  "containerd.io=${CONTAINERD_VERSION}" \
  "docker-buildx-plugin=${BUILDX_VERSION}" \
  "docker-ce=${DOCKER_ENGINE_VERSION}" \
  "docker-ce-cli=${DOCKER_CLI_VERSION}" \
  "docker-compose-plugin=${COMPOSE_VERSION}"
apt-mark hold containerd.io docker-buildx-plugin docker-ce docker-ce-cli docker-compose-plugin

installer=$(mktemp)
trap 'rm -f "$installer"' EXIT
curl --fail --location --proto '=https' --tlsv1.2 \
  --output "$installer" \
  https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
printf '%s  %s\n' "$OPS_AGENT_INSTALLER_SHA256" "$installer" | sha256sum --check --strict
bash "$installer" --also-install --version="$OPS_AGENT_VERSION"

install -d -m 0755 /opt/research
install -d -m 0755 /etc/docker
cat >/etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-file": "5",
    "max-size": "20m"
  }
}
EOF

cat >/etc/sysctl.d/60-jarvis-hardening.conf <<'EOF'
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
kernel.dmesg_restrict = 1
kernel.kptr_restrict = 2
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
EOF
sysctl --system >/dev/null

install -d -m 0755 /etc/ssh/sshd_config.d
cat >/etc/ssh/sshd_config.d/60-jarvis.conf <<'EOF'
KbdInteractiveAuthentication no
PasswordAuthentication no
PermitRootLogin no
X11Forwarding no
EOF
sshd -t

# Hosts change only by reviewed image replacement. Prevent periodic package
# jobs from silently changing a running machine underneath Terraform.
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer
systemctl mask apt-daily.service apt-daily-upgrade.service
systemctl enable docker.service google-cloud-ops-agent.service
systemctl restart docker.service google-cloud-ops-agent.service

docker_installed=$(dpkg-query -W -f='${Version}' docker-ce)
docker_cli_installed=$(dpkg-query -W -f='${Version}' docker-ce-cli)
containerd_installed=$(dpkg-query -W -f='${Version}' containerd.io)
buildx_installed=$(dpkg-query -W -f='${Version}' docker-buildx-plugin)
compose_installed=$(dpkg-query -W -f='${Version}' docker-compose-plugin)
ops_agent_installed=$(dpkg-query -W -f='${Version}' google-cloud-ops-agent)
rsync_installed=$(dpkg-query -W -f='${Version}' rsync)
cat >/etc/jarvis-host-image.json <<EOF
{
  "schema_version": 1,
  "image_name": "${IMAGE_NAME}",
  "git_revision": "${GIT_REVISION}",
  "source_image": "${SOURCE_IMAGE}",
  "verified_downloads": {
    "docker_repository_key_sha256": "${DOCKER_REPO_KEY_SHA256}",
    "ops_agent_installer_sha256": "${OPS_AGENT_INSTALLER_SHA256}"
  },
  "packages": {
    "containerd.io": "${containerd_installed}",
    "docker-buildx-plugin": "${buildx_installed}",
    "docker-ce": "${docker_installed}",
    "docker-ce-cli": "${docker_cli_installed}",
    "docker-compose-plugin": "${compose_installed}",
    "google-cloud-ops-agent": "${ops_agent_installed}",
    "rsync": "${rsync_installed}"
  },
  "update_strategy": "replace-image"
}
EOF
chmod 0444 /etc/jarvis-host-image.json

apt-get clean
rm -rf /var/lib/apt/lists/*
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
