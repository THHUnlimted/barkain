#!/usr/bin/env bash
# Barkain — SSH Tunnel to EC2 Scraper Containers
# Run this on your Mac to connect local ports to EC2.
#
# Usage:
#   bash scripts/ec2_tunnel.sh <EC2_IP> [SSH_KEY_PATH]
#
# Examples:
#   bash scripts/ec2_tunnel.sh 54.123.45.67
#   bash scripts/ec2_tunnel.sh 54.123.45.67 ~/.ssh/barkain.pem
#
# After running, your local backend's CONTAINER_URL_PATTERN=http://localhost:{port}
# connects to EC2 containers with zero code changes.
set -euo pipefail

EC2_IP="${1:-}"
SSH_KEY="${2:-$HOME/.ssh/id_rsa}"

if [ -z "$EC2_IP" ]; then
    echo "Usage: bash scripts/ec2_tunnel.sh <EC2_IP> [SSH_KEY_PATH]"
    echo ""
    echo "  EC2_IP:       Public IP or Elastic IP of the EC2 instance"
    echo "  SSH_KEY_PATH: Path to SSH private key (default: ~/.ssh/id_rsa)"
    exit 1
fi

if [ ! -f "$SSH_KEY" ]; then
    echo "ERROR: SSH key not found at ${SSH_KEY}"
    echo "Provide the correct path: bash scripts/ec2_tunnel.sh ${EC2_IP} /path/to/key.pem"
    exit 1
fi

echo "========================================="
echo "  Barkain SSH Tunnel to EC2"
echo "========================================="
echo "  EC2 IP:  ${EC2_IP}"
echo "  SSH Key: ${SSH_KEY}"
echo ""

# Kill any existing tunnel
EXISTING=$(pgrep -f "ssh.*${EC2_IP}.*LocalForward" 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
    echo "Killing existing tunnel (PID: ${EXISTING})..."
    kill "$EXISTING" 2>/dev/null || true
    sleep 1
fi

# Open tunnel — all 11 scraper ports
echo "Opening SSH tunnel (ports 8081-8091)..."
ssh -i "$SSH_KEY" \
    -L 8081:localhost:8081 \
    -L 8082:localhost:8082 \
    -L 8083:localhost:8083 \
    -L 8084:localhost:8084 \
    -L 8085:localhost:8085 \
    -L 8086:localhost:8086 \
    -L 8087:localhost:8087 \
    -L 8088:localhost:8088 \
    -L 8089:localhost:8089 \
    -L 8090:localhost:8090 \
    -L 8091:localhost:8091 \
    -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=60 \
    -N -f "ubuntu@${EC2_IP}"

echo "Tunnel established."
echo ""

# Verify with health checks
echo "Verifying connections..."
ACTIVE=0
for pair in "amazon:8081" "best_buy:8082" "walmart:8083"; do
    retailer="${pair%%:*}"
    port="${pair##*:}"

    STATUS=$(curl -s --max-time 3 "http://localhost:${port}/health" 2>/dev/null || echo "")
    if [ -n "$STATUS" ]; then
        echo "  [OK]   ${retailer} (localhost:${port})"
        ACTIVE=$((ACTIVE + 1))
    else
        echo "  [--]   ${retailer} (localhost:${port}) — not responding (may not be running on EC2)"
    fi
done

echo ""
if [ "$ACTIVE" -gt 0 ]; then
    echo "Tunnel active. ${ACTIVE} container(s) reachable."
    echo "Your local backend can now reach EC2 containers at localhost:8081-8091."
    echo ""
    echo "To close tunnel: kill \$(pgrep -f 'ssh.*${EC2_IP}.*-N')"
else
    echo "Tunnel open but no containers responding."
    echo "Make sure containers are running on EC2: ssh -i ${SSH_KEY} ubuntu@${EC2_IP} 'docker ps'"
fi
