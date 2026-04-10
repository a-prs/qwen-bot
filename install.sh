#!/bin/bash

# QwenClaw Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/a-prs/QwenClaw/main/install.sh -o /tmp/install.sh && sudo bash /tmp/install.sh

INSTALL_DIR="/opt/qwenbot"
REPO_URL="https://github.com/a-prs/QwenClaw.git"
SERVICE_NAME="qwenbot"
NODE_MIN_VERSION=18
SELF_URL="https://raw.githubusercontent.com/a-prs/QwenClaw/main/install.sh"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
fail()  { echo -e "${RED}[x]${NC} $1"; exit 1; }

# ============================================================
#  Self-relaunch: if piped (curl|bash), re-download and re-exec
#  This fixes: stdin for read, process survives SSH disconnect
# ============================================================
if [ ! -t 0 ]; then
    SELF="/tmp/qwenclaw-install.sh"
    echo -e "${GREEN}[+]${NC} Piped mode detected. Re-downloading for interactive install..."
    curl -fsSL "$SELF_URL" -o "$SELF"
    chmod +x "$SELF"
    exec bash "$SELF" "$@"
fi

set -e

echo ""
echo -e "${BOLD}======================================${NC}"
echo -e "${BOLD}    QwenClaw Installer${NC}"
echo -e "${BOLD}    AI Assistant via Telegram${NC}"
echo -e "${BOLD}======================================${NC}"
echo ""

# --- Upgrade mode ---
if [[ "$1" == "--upgrade" ]]; then
    info "Upgrading QwenClaw..."
    cd "$INSTALL_DIR" && git pull
    "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/bot/requirements.txt"
    systemctl restart "$SERVICE_NAME"
    info "Done! Check: systemctl status $SERVICE_NAME"
    exit 0
fi

# --- Check root ---
if [[ $EUID -ne 0 ]]; then
    fail "Run as root: sudo bash $0"
fi

# --- Check OS ---
if ! grep -qiE "ubuntu|debian" /etc/os-release 2>/dev/null; then
    warn "This script is designed for Ubuntu/Debian. Proceeding anyway..."
fi

# --- Check if already installed ---
if [[ -d "$INSTALL_DIR/bot" ]]; then
    warn "QwenClaw is already installed at $INSTALL_DIR"
    read -p "  Reinstall? (y/N): " reinstall
    if [[ "$reinstall" != "y" && "$reinstall" != "Y" ]]; then
        echo ""
        info "To update: cd $INSTALL_DIR && git pull && systemctl restart $SERVICE_NAME"
        exit 0
    fi
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
fi


# ============================================================
#  Step 1: System dependencies
# ============================================================
info "Installing system packages..."
apt-get update -qq || fail "apt-get update failed"
apt-get install -y python3 python3-venv python3-pip git curl ca-certificates gnupg sudo 2>&1 | tail -3
info "System packages installed"


# ============================================================
#  Step 2: Node.js
# ============================================================
need_node=false

if command -v node &>/dev/null; then
    NODE_CUR=$(node -v | cut -d. -f1 | tr -d v)
    if [[ "$NODE_CUR" -lt "$NODE_MIN_VERSION" ]]; then
        warn "Node.js v${NODE_CUR} found, need >= ${NODE_MIN_VERSION}"
        need_node=true
    else
        info "Node.js $(node -v) OK"
    fi
else
    need_node=true
fi

if [[ "$need_node" == "true" ]]; then
    info "Installing Node.js 20.x (this may take a minute)..."

    mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg 2>/dev/null

    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list

    apt-get update -qq || fail "Failed to update after adding NodeSource"
    apt-get install -y nodejs 2>&1 | tail -3 || fail "Failed to install Node.js"

    command -v node &>/dev/null || fail "Node.js not found after install"
    command -v npm  &>/dev/null || fail "npm not found after install"
    info "Node.js $(node -v) installed"
fi


# ============================================================
#  Step 3: Qwen Code CLI
# ============================================================
if command -v qwen &>/dev/null; then
    info "Qwen Code CLI found"
else
    info "Installing Qwen Code CLI via npm..."
    npm install -g @qwen-code/qwen-code@latest 2>&1 | tail -3 || fail "Failed to install Qwen Code CLI"

    if ! command -v qwen &>/dev/null; then
        NPM_BIN=$(npm config get prefix)/bin
        if [[ -f "$NPM_BIN/qwen" ]]; then
            ln -sf "$NPM_BIN/qwen" /usr/local/bin/qwen
        else
            fail "Qwen Code CLI not found after install"
        fi
    fi
    info "Qwen Code CLI installed"
fi


# ============================================================
#  Step 4: Create system user
# ============================================================
if id -u qwenbot &>/dev/null; then
    info "User 'qwenbot' exists"
else
    info "Creating user 'qwenbot'..."
    useradd -r -d "$INSTALL_DIR" -s /bin/bash qwenbot
fi


# ============================================================
#  Step 5: Clone repository
# ============================================================
info "Downloading QwenClaw..."

if [[ -d "$INSTALL_DIR/.git" ]]; then
    cd "$INSTALL_DIR" && git pull
    info "Repository updated"
else
    if [[ -d "$INSTALL_DIR" ]]; then
        [[ -f "$INSTALL_DIR/.env" ]] && cp "$INSTALL_DIR/.env" /tmp/_qwenbot_env_backup
        rm -rf "$INSTALL_DIR"
    fi

    git clone "$REPO_URL" "$INSTALL_DIR" || fail "Failed to clone: $REPO_URL"

    [[ -f /tmp/_qwenbot_env_backup ]] && mv /tmp/_qwenbot_env_backup "$INSTALL_DIR/.env"
    info "Repository cloned"
fi


# ============================================================
#  Step 6: Python venv + dependencies
# ============================================================
info "Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/.venv" || fail "Failed to create venv"

info "Upgrading pip..."
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip 2>&1 | tail -1

info "Installing Python dependencies (this takes 1-2 minutes)..."
echo "  Downloading: aiogram, httpx, python-dotenv..."

# Run pip with progress, show last lines
"$INSTALL_DIR/.venv/bin/pip" install \
    --progress-bar on \
    -r "$INSTALL_DIR/bot/requirements.txt" 2>&1 \
    | while IFS= read -r line; do
        # Show download/install progress
        if [[ "$line" == *"Collecting"* ]]; then
            echo -e "  ${GREEN}>>>${NC} $line"
        elif [[ "$line" == *"Downloading"* ]]; then
            echo -e "  ${GREEN}>>>${NC} $line"
        elif [[ "$line" == *"Installing"* ]]; then
            echo -e "  ${GREEN}>>>${NC} $line"
        elif [[ "$line" == *"Successfully"* ]]; then
            echo -e "  ${GREEN}>>>${NC} $line"
        elif [[ "$line" == *"ERROR"* ]] || [[ "$line" == *"error"* ]]; then
            echo -e "  ${RED}!!!${NC} $line"
        fi
    done

# Verify installation
if ! "$INSTALL_DIR/.venv/bin/python" -c "import aiogram" 2>/dev/null; then
    warn "aiogram not found, retrying installation..."
    "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/bot/requirements.txt" || fail "Failed to install Python dependencies"
fi

info "Python environment ready"


# ============================================================
#  Step 7: Create runtime directories
# ============================================================
mkdir -p "$INSTALL_DIR/workspace"
mkdir -p "$INSTALL_DIR/data"


# ============================================================
#  Step 8: Configuration (.env)
# ============================================================
if [[ -f "$INSTALL_DIR/.env" ]]; then
    info "Config .env already exists, keeping it"
else
    echo ""
    echo -e "${BOLD}======================================${NC}"
    echo -e "${BOLD}    Configuration${NC}"
    echo -e "${BOLD}======================================${NC}"
    echo ""

    echo "  Step 1: Telegram Bot Token"
    echo "  Get it from @BotFather in Telegram"
    echo ""
    while true; do
        read -p "  Bot token: " BOT_TOKEN
        if [[ "$BOT_TOKEN" =~ ^[0-9]+:.+$ ]]; then
            break
        fi
        warn "  Invalid format. Should look like: 123456:ABC-DEF..."
    done

    echo ""

    echo "  Step 2: Your Telegram Chat ID"
    echo "  Get it from @userinfobot in Telegram"
    echo ""
    while true; do
        read -p "  Chat ID: " CHAT_ID
        if [[ "$CHAT_ID" =~ ^[0-9]+$ ]]; then
            break
        fi
        warn "  Should be a number like: 987654321"
    done

    echo ""

    echo "  Step 3 (optional): Groq API Key for voice messages"
    echo "  Free key: https://console.groq.com/keys"
    echo "  Press Enter to skip"
    echo ""
    read -p "  Groq API key: " GROQ_KEY

    cat > "$INSTALL_DIR/.env" << ENVEOF
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
TELEGRAM_CHAT_ID=$CHAT_ID
GROQ_API_KEY=$GROQ_KEY
ENVEOF

    info "Config saved to $INSTALL_DIR/.env"
fi


# ============================================================
#  Step 9: Permissions
# ============================================================
chown -R qwenbot:qwenbot "$INSTALL_DIR"

echo "qwenbot ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart qwenbot" > /etc/sudoers.d/qwenbot
chmod 440 /etc/sudoers.d/qwenbot
info "Permissions configured"


# ============================================================
#  Step 10: Qwen Code Authorization
# ============================================================
echo ""
echo -e "${BOLD}======================================${NC}"
echo -e "${BOLD}    Qwen Code Authorization${NC}"
echo -e "${BOLD}======================================${NC}"
echo ""
echo "  This may take 2 attempts:"
echo ""
echo "  1. A link will appear — open it in YOUR browser"
echo "  2. Register/login at Qwen website if needed"
echo "  3. If you end up in Qwen chat instead of OAuth,"
echo "     come back and we'll try again"
echo ""
read -p "  Press Enter to start..."

echo ""
sudo -u qwenbot bash -c 'export PATH="/usr/local/bin:/usr/bin:$PATH" && qwen auth login' || true

echo ""
read -p "  Authorization OK? (y = yes / Enter = try again): " auth_ok

if [[ "$auth_ok" != "y" && "$auth_ok" != "Y" ]]; then
    info "Trying again..."
    echo ""
    sudo -u qwenbot bash -c 'export PATH="/usr/local/bin:/usr/bin:$PATH" && qwen auth login' || true

    echo ""
    read -p "  Now? (y/n): " auth_ok2
    if [[ "$auth_ok2" != "y" && "$auth_ok2" != "Y" ]]; then
        warn "You can authorize later: sudo -u qwenbot qwen auth login"
    fi
fi


# ============================================================
#  Step 11: systemd service
# ============================================================
info "Setting up systemd service..."
cp "$INSTALL_DIR/qwenbot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" -q
systemctl start "$SERVICE_NAME"


# ============================================================
#  Step 12: Verify
# ============================================================
sleep 3

echo ""
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo -e "${BOLD}======================================${NC}"
    echo -e "    ${GREEN}QwenClaw is running!${NC}"
    echo -e "${BOLD}======================================${NC}"
    echo ""
    echo "  Send a message to your bot in Telegram."
    echo ""
    echo "  Commands:"
    echo "    systemctl status $SERVICE_NAME"
    echo "    journalctl -u $SERVICE_NAME -f"
    echo "    systemctl restart $SERVICE_NAME"
    echo ""
    echo "  Update from Telegram: /update"
    echo ""
    if [[ -z "$GROQ_KEY" ]]; then
        echo "  Voice: disabled (add via /setup in Telegram)"
        echo ""
    fi
else
    warn "Service failed to start. Check logs:"
    echo ""
    journalctl -u "$SERVICE_NAME" --no-pager -n 15
    echo ""
    echo "  Fix the issue and run: systemctl start $SERVICE_NAME"
fi

# Cleanup
rm -f /tmp/qwenclaw-install.sh 2>/dev/null
