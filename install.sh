#!/bin/bash
set -e

# ─────────────────────────────────────────────────────────────
#  肘子播放器 — 安装脚本
#  为当前用户安装依赖并注册桌面启动器
# ─────────────────────────────────────────────────────────────

APP_NAME="肘子播放器"
INSTALL_DIR="$HOME/.local/share/zhouzi-player"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "📦 安装 $APP_NAME ..."

# ── 1. 系统依赖 ──

echo "🔧 安装系统依赖 ..."
sudo apt update -qq
sudo apt install -y -qq \
    mpv ffmpeg \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-notify-0.7 \
    python3-mutagen

# ── 2. Python 依赖 ──

# mutagen 已通过 apt 安装，但如果 pip 版本更新可在此安装
# pip3 install --user --upgrade mutagen 2>/dev/null || true

# ── 3. 复制程序文件 ──

echo "📁 复制程序到 $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/player.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/play.sh" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/zhouzi-player.svg" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/player.py" "$INSTALL_DIR/play.sh"

# ── 4. 创建桌面启动器 ──

echo "🪟 注册桌面启动器"
mkdir -p "$APP_DIR"
sed "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    "$SCRIPT_DIR/zhouzi.player.desktop" > "$APP_DIR/zhouzi.player.desktop"
chmod +x "$APP_DIR/zhouzi.player.desktop"

# ── 5. 安装图标 ──

echo "🖼️ 安装图标"
mkdir -p "$ICON_DIR"
# SVG 图标放 scalable 目录，不要放固定尺寸目录
cp "$SCRIPT_DIR/zhouzi-player.svg" "$ICON_DIR/zhouzi-player.svg"

# 刷新图标缓存（如果有的话）
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

# ── 6. 可选：添加到 PATH ──

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/zhouzi-player" << 'EOF'
#!/bin/bash
exec "$HOME/.local/share/zhouzi-player/play.sh"
EOF
chmod +x "$BIN_DIR/zhouzi-player"

echo ""
echo "✅ 安装完成！"
echo ""
echo "你可以在应用列表中找到「肘子播放器」，"
echo "或在终端执行: zhouzi-player"
echo ""
echo "首次启动后，点击 ☰ 菜单 → 文件位置，选择你的音乐文件夹。"
