#!/usr/bin/env bash
# =============================================================================
# Knock - Server Setup Script
# Target: Ubuntu 24.04 LTS (DigitalOcean Droplet)
# Run as root: bash setup-server.sh
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
DEPLOY_USER="deploy"
KNOCK_DIR="/opt/knock"
NODE_VERSION="22"
NVM_VERSION="0.40.0"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[SETUP]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# -----------------------------------------------------------------------------
# Pre-flight checks
# -----------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root."
    exit 1
fi

if ! grep -q "Ubuntu" /etc/os-release 2>/dev/null; then
    warn "This script is designed for Ubuntu. Proceed with caution."
fi

log "Starting Knock server setup..."

# -----------------------------------------------------------------------------
# 1. System updates and essentials
# -----------------------------------------------------------------------------
log "Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl \
    wget \
    git \
    build-essential \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    unzip \
    htop \
    jq \
    fail2ban \
    logrotate \
    ufw

log "System packages updated."

# -----------------------------------------------------------------------------
# 2. Docker & Docker Compose plugin
# -----------------------------------------------------------------------------
log "Installing Docker..."
if command -v docker &>/dev/null; then
    warn "Docker is already installed: $(docker --version)"
else
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -qq
    apt-get install -y -qq \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin

    systemctl enable docker
    systemctl start docker
    log "Docker installed: $(docker --version)"
    log "Docker Compose installed: $(docker compose version)"
fi

# -----------------------------------------------------------------------------
# 3. Caddy (reverse proxy with automatic HTTPS)
# -----------------------------------------------------------------------------
log "Installing Caddy..."
if command -v caddy &>/dev/null; then
    warn "Caddy is already installed: $(caddy version)"
else
    apt-get install -y -qq debian-keyring debian-archive-keyring
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
        gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | \
        tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq caddy

    # Stop the system caddy service -- we run via Docker instead
    systemctl stop caddy || true
    systemctl disable caddy || true
    log "Caddy installed: $(caddy version)"
fi

# -----------------------------------------------------------------------------
# 4. Create deploy user
# -----------------------------------------------------------------------------
log "Creating deploy user..."
if id "$DEPLOY_USER" &>/dev/null; then
    warn "User '$DEPLOY_USER' already exists."
else
    adduser --disabled-password --gecos "Knock Deploy" "$DEPLOY_USER"
    log "User '$DEPLOY_USER' created."
fi

# Add deploy user to docker group
usermod -aG docker "$DEPLOY_USER"

# Set up SSH directory for deploy user
DEPLOY_HOME="/home/$DEPLOY_USER"
mkdir -p "$DEPLOY_HOME/.ssh"
chmod 700 "$DEPLOY_HOME/.ssh"
touch "$DEPLOY_HOME/.ssh/authorized_keys"
chmod 600 "$DEPLOY_HOME/.ssh/authorized_keys"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_HOME/.ssh"

# If root has authorized_keys, copy them to deploy user
if [[ -f /root/.ssh/authorized_keys ]]; then
    cp /root/.ssh/authorized_keys "$DEPLOY_HOME/.ssh/authorized_keys"
    chown "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_HOME/.ssh/authorized_keys"
    log "Copied root authorized_keys to deploy user."
fi

# Allow deploy user to run docker without sudo (via group) and limited sudo
echo "$DEPLOY_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart docker, /usr/bin/docker compose *" > \
    /etc/sudoers.d/deploy
chmod 440 /etc/sudoers.d/deploy

# -----------------------------------------------------------------------------
# 5. UFW Firewall
# -----------------------------------------------------------------------------
log "Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
ufw allow 80/tcp comment "HTTP"
ufw allow 443/tcp comment "HTTPS"
ufw --force enable
ufw status verbose
log "Firewall configured: SSH (22), HTTP (80), HTTPS (443) only."

# -----------------------------------------------------------------------------
# 6. Create application directory
# -----------------------------------------------------------------------------
log "Creating application directory at $KNOCK_DIR..."
mkdir -p "$KNOCK_DIR"
mkdir -p "$KNOCK_DIR/backups"
mkdir -p "$KNOCK_DIR/logs"
mkdir -p "$KNOCK_DIR/public"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$KNOCK_DIR"
chmod 750 "$KNOCK_DIR"
log "Application directory created."

# -----------------------------------------------------------------------------
# 7. SSH hardening (key auth only, disable password)
# -----------------------------------------------------------------------------
log "Hardening SSH configuration..."
SSHD_CONFIG="/etc/ssh/sshd_config"
cp "$SSHD_CONFIG" "${SSHD_CONFIG}.bak.$(date +%Y%m%d)"

# Apply SSH hardening
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD_CONFIG"
sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' "$SSHD_CONFIG"
sed -i 's/^#\?UsePAM.*/UsePAM no/' "$SSHD_CONFIG"
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSHD_CONFIG"
sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' "$SSHD_CONFIG"
sed -i 's/^#\?MaxAuthTries.*/MaxAuthTries 3/' "$SSHD_CONFIG"
sed -i 's/^#\?ClientAliveInterval.*/ClientAliveInterval 300/' "$SSHD_CONFIG"
sed -i 's/^#\?ClientAliveCountMax.*/ClientAliveCountMax 2/' "$SSHD_CONFIG"

# Validate config before restarting
if sshd -t; then
    systemctl restart sshd
    log "SSH hardened: password auth disabled, key auth only."
else
    err "SSH config validation failed. Restoring backup..."
    cp "${SSHD_CONFIG}.bak.$(date +%Y%m%d)" "$SSHD_CONFIG"
    systemctl restart sshd
    err "SSH config restored from backup."
fi

# -----------------------------------------------------------------------------
# 8. Install nvm + Node.js
# -----------------------------------------------------------------------------
log "Installing nvm and Node.js $NODE_VERSION for deploy user..."
sudo -u "$DEPLOY_USER" bash -c "
    export HOME=/home/$DEPLOY_USER
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v${NVM_VERSION}/install.sh | bash
    export NVM_DIR=\"\$HOME/.nvm\"
    [ -s \"\$NVM_DIR/nvm.sh\" ] && . \"\$NVM_DIR/nvm.sh\"
    nvm install $NODE_VERSION
    nvm alias default $NODE_VERSION
    nvm use default
    node --version
    npm --version
"
log "Node.js $NODE_VERSION installed for deploy user."

# -----------------------------------------------------------------------------
# 9. Configure fail2ban
# -----------------------------------------------------------------------------
log "Configuring fail2ban..."
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s
maxretry = 3
bantime = 7200
EOF

systemctl enable fail2ban
systemctl restart fail2ban
log "fail2ban configured."

# -----------------------------------------------------------------------------
# 10. System tuning
# -----------------------------------------------------------------------------
log "Applying system tuning..."
cat >> /etc/sysctl.d/99-knock.conf <<'EOF'
# Network tuning
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# File descriptor limits
fs.file-max = 2097152

# VM tuning for database workloads
vm.overcommit_memory = 1
vm.swappiness = 10
EOF
sysctl -p /etc/sysctl.d/99-knock.conf

# Increase file descriptor limits for deploy user
cat >> /etc/security/limits.d/knock.conf <<EOF
$DEPLOY_USER soft nofile 65535
$DEPLOY_USER hard nofile 65535
EOF

log "System tuning applied."

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo ""
log "============================================"
log "  Knock server setup complete!"
log "============================================"
log ""
log "Next steps:"
log "  1. Add your SSH public key to /home/$DEPLOY_USER/.ssh/authorized_keys"
log "  2. Test SSH login as '$DEPLOY_USER' before closing this session"
log "  3. Clone the repo: cd $KNOCK_DIR && git clone <repo-url> ."
log "  4. Copy .env.example to .env and fill in secrets"
log "  5. Run: docker compose up -d"
log ""
log "Important paths:"
log "  App directory:  $KNOCK_DIR"
log "  Backups:        $KNOCK_DIR/backups"
log "  Logs:           $KNOCK_DIR/logs"
log ""
