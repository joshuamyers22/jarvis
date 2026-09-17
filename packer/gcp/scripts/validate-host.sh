#!/usr/bin/env bash
set -euo pipefail

source /etc/os-release
[[ "$ID" == "debian" && "$VERSION_ID" == "12" ]]
test -r /etc/jarvis-host-image.json
test -d /opt/research
test "$(stat -c '%a' /opt/research)" = "755"

dpkg-query -W containerd.io docker-buildx-plugin docker-ce docker-ce-cli docker-compose-plugin google-cloud-ops-agent rsync >/dev/null
test "$(dpkg-query -W -f='${Version}' containerd.io)" = "$CONTAINERD_VERSION"
test "$(dpkg-query -W -f='${Version}' docker-buildx-plugin)" = "$BUILDX_VERSION"
test "$(dpkg-query -W -f='${Version}' docker-ce)" = "$DOCKER_ENGINE_VERSION"
test "$(dpkg-query -W -f='${Version}' docker-ce-cli)" = "$DOCKER_CLI_VERSION"
test "$(dpkg-query -W -f='${Version}' docker-compose-plugin)" = "$COMPOSE_VERSION"
[[ "$(dpkg-query -W -f='${Version}' google-cloud-ops-agent)" == "$OPS_AGENT_VERSION"* ]]
test "$(dpkg-query -W -f='${Version}' rsync)" = "$RSYNC_VERSION"
docker --version
docker buildx version
docker compose version
systemctl is-enabled docker.service
systemctl is-active --quiet docker.service
systemctl is-enabled google-cloud-ops-agent.service
systemctl is-active --quiet google-cloud-ops-agent.service

test "$(sysctl -n kernel.kptr_restrict)" = "2"
test "$(sysctl -n kernel.dmesg_restrict)" = "1"
test "$(sysctl -n net.ipv4.conf.all.accept_redirects)" = "0"
sshd -t

apt_daily_state=$(systemctl is-enabled apt-daily.timer 2>/dev/null || true)
apt_upgrade_state=$(systemctl is-enabled apt-daily-upgrade.timer 2>/dev/null || true)
[[ "$apt_daily_state" =~ ^(disabled|masked)$ ]]
[[ "$apt_upgrade_state" =~ ^(disabled|masked)$ ]]
grep -Fq '"update_strategy": "replace-image"' /etc/jarvis-host-image.json
grep -Fq "\"git_revision\": \"${GIT_REVISION}\"" /etc/jarvis-host-image.json
grep -Fq "\"docker_repository_key_sha256\": \"${DOCKER_REPO_KEY_SHA256}\"" /etc/jarvis-host-image.json
grep -Fq "\"ops_agent_installer_sha256\": \"${OPS_AGENT_INSTALLER_SHA256}\"" /etc/jarvis-host-image.json

# A reusable machine image must not contain builder credentials or SSH keys.
test ! -e /root/.config/gcloud/application_default_credentials.json
test ! -e /home/packer/.config/gcloud/application_default_credentials.json
find /root /home -xdev -type f \( -name '*.pem' -o -name '*.p12' \) -print -quit | grep -q . && {
  echo "credential or SSH material remains in the image" >&2
  exit 1
}
