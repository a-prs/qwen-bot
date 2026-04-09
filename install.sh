#!/bin/bash
set -e

# QwenBot Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/a-prs/qwen-bot/main/install.sh | sudo bash

INSTALL_DIR="/opt/qwenbot"
REPO_URL="https://github.com/a-prs/qwen-bot.git"
SERVICE_NAME="qwenbot"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[x]${NC} $1"; exit 1; }

echo ""
echo "======================================"
echo "    QwenBot Installer"
echo "    AI Assistant via Telegram"
echo "======================================"
echo ""

# --- Upgrade mode ---
if [[ "$1" == "--upgrade" ]]; then
    info "Upgrading QwenBot..."
    cd "$INSTALL_DIR" && git pull
    "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/bot/requirements.txt"
    systemctl restart "$SERVICE_NAME"
    info "Done! Check: systemctl status $SERVICE_NAME"
    exit 0
fi

# --- Check root ---
if [[ $EUID -ne 0 ]]; then
    error "Run as root: sudo bash install.sh"
fi

# --- Check OS ---
if ! grep -qiE "ubuntu|debian" /etc/os-release 2>/dev/null; then
    warn "This script is designed for Ubuntu/Debian. Proceeding anyway..."
fi

# --- Check if already installed ---
if [[ -d "$INSTALL_DIR/bot" ]]; then
    warn "QwenBot is already installed at $INSTALL_DIR"
    read -p "Reinstall? (y/N): " reinstall
    if [[ "$reinstall" != "y" && "$reinstall" != "Y" ]]; then
        info "Use --upgrade to update: curl ... | bash -s -- --upgrade"
        exit 0
    fi
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
fi

# === Step 1: System dependencies ===
info "Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv git curl > /dev/null

# === Step 2: Node.js (for Qwen Code CLI) ===
NODE_MIN_VERSION=18

install_node() {
    info "Installing Node.js 20.x..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1
    apt-get install -y -qq nodejs > /dev/null
}

if command -v node &> /dev/null; then
    NODE_VERSION=$(node -v | cut -d. -f1 | tr -d v)
    if [[ "$NODE_VERSION" -lt "$NODE_MIN_VERSION" ]]; then
        warn "Node.js $NODE_VERSION found, need >= $NODE_MIN_VERSION"
        install_node
    else
        info "Node.js $(node -v) found"
    fi
else
    install_node
fi

# === Step 3: Qwen Code CLI ===
if command -v qwen &> /dev/null; then
    info "Qwen Code CLI found: $(qwen --version 2>/dev/null || echo 'installed')"
else
    info "Installing Qwen Code CLI..."
    npm install -g @qwen-code/qwen-code@latest > /dev/null 2>&1
    if command -v qwen &> /dev/null; then
        info "Qwen Code CLI installed"
    else
        error "Failed to install Qwen Code CLI. Check npm."
    fi
fi

# === Step 4: Create user ===
if id -u qwenbot &>/dev/null; then
    info "User 'qwenbot' exists"
else
    info "Creating user 'qwenbot'..."
    useradd -r -m -d "$INSTALL_DIR" -s /bin/bash qwenbot
fi

# === Step 5: Clone repository ===
info "Downloading QwenBot..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
    cd "$INSTALL_DIR" && git pull
else
    rm -rf "$INSTALL_DIR/bot" 2>/dev/null || true
    git clone "$REPO_URL" "$INSTALL_DIR" 2>/dev/null || {
        # If git clone fails (repo doesn't exist yet), copy from current dir
        warn "Git clone failed. If running locally, copy files manually."
        error "Repository not found: $REPO_URL"
    }
fi

# === Step 6: Python venv ===
info "Setting up Python environment..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/bot/requirements.txt"

# === Step 7: Create directories ===
mkdir -p "$INSTALL_DIR/workspace"
mkdir -p "$INSTALL_DIR/data"

# === Step 8: Configuration (.env) ===
if [[ -f "$INSTALL_DIR/.env" ]]; then
    info "Config .env already exists, keeping it"
else
    echo ""
    echo "======================================"
    echo "    Configuration"
    echo "======================================"
    echo ""

    # Telegram Bot Token
    echo "Step 1: Telegram Bot Token"
    echo "  Get it from @BotFather in Telegram"
    echo ""
    while true; do
        read -p "  Bot token: " BOT_TOKEN
        if [[ "$BOT_TOKEN" =~ ^[0-9]+:.+$ ]]; then
            break
        fi
        warn "Invalid format. Should look like: 123456:ABC-DEF..."
    done

    echo ""

    # Admin Chat ID
    echo "Step 2: Your Telegram Chat ID"
    echo "  Get it from @userinfobot in Telegram"
    echo ""
    while true; do
        read -p "  Chat ID: " CHAT_ID
        if [[ "$CHAT_ID" =~ ^[0-9]+$ ]]; then
            break
        fi
        warn "Should be a number like: 987654321"
    done

    echo ""

    # Groq API Key (optional)
    echo "Step 3 (optional): Groq API Key for voice messages"
    echo "  Free key: https://console.groq.com/keys"
    echo "  Press Enter to skip"
    echo ""
    read -p "  Groq API key: " GROQ_KEY

    # Write .env
    cat > "$INSTALL_DIR/.env" << EOF
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
TELEGRAM_CHAT_ID=$CHAT_ID
GROQ_API_KEY=$GROQ_KEY
EOF

    info "Config saved to $INSTALL_DIR/.env"
fi

# === Step 9: Fix permissions ===
chown -R qwenbot:qwenbot "$INSTALL_DIR"

# === Step 10: Qwen Code auth ===
echo ""
echo "======================================"
echo "    Qwen Code Authorization"
echo "======================================"
echo ""
echo "  This may take 2 attempts:"
echo "  1. First time: register/login at Qwen website"
echo "  2. Second time: complete OAuth authorization"
echo ""
echo "  A link will appear below."
echo "  Open it in your browser, follow instructions."
echo ""
read -p "  Press Enter to start authorization..."

# Install qwen for the qwenbot user
sudo -u qwenbot bash -c 'export PATH="/usr/local/bin:/usr/bin:$PATH" && qwen auth login' || true

echo ""
read -p "  Did authorization succeed? (y = yes / Enter = try again): " auth_ok

if [[ "$auth_ok" != "y" && "$auth_ok" != "Y" ]]; then
    info "Trying again..."
    sudo -u qwenbot bash -c 'export PATH="/usr/local/bin:/usr/bin:$PATH" && qwen auth login' || true

    echo ""
    read -p "  Now? (y/n): " auth_ok2
    if [[ "$auth_ok2" != "y" && "$auth_ok2" != "Y" ]]; then
        warn "You can authorize later: sudo -u qwenbot qwen auth login"
    fi
fi

# === Step 11: Install systemd service ===
info "Setting up systemd service..."
cp "$INSTALL_DIR/qwenbot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start "$SERVICE_NAME"

# === Step 12: Verify ===
sleep 3
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo ""
    echo "======================================"
    echo -e "    ${GREEN}QwenBot is running!${NC}"
    echo "======================================"
    echo ""
    echo "  Send a message to your bot in Telegram."
    echo ""
    echo "  Useful commands:"
    echo "    systemctl status $SERVICE_NAME    # check status"
    echo "    journalctl -u $SERVICE_NAME -f    # view logs"
    echo "    systemctl restart $SERVICE_NAME   # restart"
    echo ""
    echo "  To update:"
    echo "    cd $INSTALL_DIR && git pull && systemctl restart $SERVICE_NAME"
    echo ""
    if [[ -z "$GROQ_KEY" ]]; then
        echo "  Voice messages: disabled"
        echo "  To enable: add GROQ_API_KEY to $INSTALL_DIR/.env"
        echo "  Free key: https://console.groq.com/keys"
        echo ""
    fi
else
    warn "Service failed to start. Check logs:"
    echo "  journalctl -u $SERVICE_NAME --no-pager -n 20"
fi
