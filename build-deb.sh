#!/bin/bash
set -e

# ─────────────────────────────────────────────────────────────
#  肘子播放器 — .deb 打包脚本
#  用法: ./build-deb.sh
#  输出: zhouzi-player_1.0.0_all.deb
# ─────────────────────────────────────────────────────────────

APP_NAME="zhouzi-player"
VERSION="1.0.0"
ARCH="all"
PKG="${APP_NAME}_${VERSION}_${ARCH}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="/tmp/${PKG}"

echo "📦 打包肘子播放器 v${VERSION} ..."

# ── 清理 ──
rm -rf "$BUILD_DIR"

# ── 创建目录结构 ──
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/${APP_NAME}"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$BUILD_DIR/usr/share/doc/${APP_NAME}"

# ── 复制程序文件 ──
cp "$SCRIPT_DIR/player.py" "$BUILD_DIR/usr/share/${APP_NAME}/"
cp "$SCRIPT_DIR/play.sh" "$BUILD_DIR/usr/share/${APP_NAME}/"
chmod 755 "$BUILD_DIR/usr/share/${APP_NAME}/player.py"
chmod 755 "$BUILD_DIR/usr/share/${APP_NAME}/play.sh"

# ── 桌面启动器 ──
sed "s|__INSTALL_DIR__|/usr/share/${APP_NAME}|g" \
    "$SCRIPT_DIR/zhouzi.player.desktop" > "$BUILD_DIR/usr/share/applications/zhouzi.player.desktop"

# ── 图标 ──
cp "$SCRIPT_DIR/zhouzi-player.svg" "$BUILD_DIR/usr/share/icons/hicolor/scalable/apps/"

# ── 启动脚本 (/usr/bin) ──
cat > "$BUILD_DIR/usr/bin/zhouzi-player" << 'EOF'
#!/bin/bash
exec /usr/share/zhouzi-player/play.sh
EOF
chmod 755 "$BUILD_DIR/usr/bin/zhouzi-player"

# ── DEBIAN/control ──
cat > "$BUILD_DIR/DEBIAN/control" << EOF
Package: zhouzi-player
Version: ${VERSION}
Section: sound
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.9),
         python3-gi,
         python3-gi-cairo,
         python3-mutagen,
         gir1.2-gtk-4.0,
         gir1.2-adw-1,
         gir1.2-notify-0.7,
         mpv,
         ffmpeg
Maintainer: 猪手 <bao@example.com>
Description: 基于 mpv 的简易音乐播放器
 肘子播放器 — 一个简洁的本地音乐播放器，
 基于 mpv + GTK4 + Adwaita 构建，支持 MPRIS 媒体控件。
Homepage: https://github.com/bao/zhouzi-player
EOF

# ── DEBIAN/postinst ──
cat > "$BUILD_DIR/DEBIAN/postinst" << 'POSTEOF'
#!/bin/bash
set -e

# 更新图标缓存
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache /usr/share/icons/hicolor 2>/dev/null || true
fi

# 更新桌面数据库
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi

echo "✅ 肘子播放器 安装完成！"
echo "   在应用列表中可找到「肘子播放器」"
echo "   或在终端执行: zhouzi-player"
POSTEOF
chmod 755 "$BUILD_DIR/DEBIAN/postinst"

# ── DEBIAN/prerm ──
cat > "$BUILD_DIR/DEBIAN/prerm" << 'PREEOF'
#!/bin/bash
set -e
# 卸载时不做特殊处理
PREEOF
chmod 755 "$BUILD_DIR/DEBIAN/prerm"

# ── copyright ──
cat > "$BUILD_DIR/usr/share/doc/${APP_NAME}/copyright" << EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: zhouzi-player
Source: https://github.com/bao/zhouzi-player

Files: *
License: GPL-3.0+
EOF

# ── 打包 ──
dpkg-deb --build "$BUILD_DIR" >/dev/null

# ── 复制到当前目录 ──
cp "/tmp/${PKG}.deb" "$SCRIPT_DIR/${PKG}.deb"
rm -rf "$BUILD_DIR"

echo ""
echo "✅ 打包完成: ${SCRIPT_DIR}/${PKG}.deb"
echo "   安装: sudo dpkg -i ${PKG}.deb"
echo "   卸载: sudo dpkg -r zhouzi-player"
