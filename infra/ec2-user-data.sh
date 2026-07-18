#!/bin/bash
set -euxo pipefail

DUCKDNS_SUBDOMAIN=polmx
DUCKDNS_TOKEN="61b1e133-f187-492d-b2af-"
# ---------------------------------------------------------------------------

if command -v yum &> /dev/null; then
  yum update -y
  yum install -y docker
  DOCKER_USER=ec2-user
else
  apt-get update -y
  apt-get install -y docker.io
  DOCKER_USER=ubuntu
fi
systemctl enable --now docker
usermod -aG docker "$DOCKER_USER"

# docker-compose-plugin no esta en los repos de todas las distros/versiones (ej. Ubuntu 22.04),
# se instala el binario directo para que funcione igual en ambas ramas.
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

cat > /usr/local/bin/duckdns-update.sh <<EOF
#!/bin/bash
curl -s "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip="
EOF
chmod +x /usr/local/bin/duckdns-update.sh

cat > /etc/systemd/system/duckdns-update.service <<'EOF'
[Unit]
Description=Actualiza DuckDNS con la IP publica al arrancar
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/duckdns-update.sh

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now duckdns-update.service
