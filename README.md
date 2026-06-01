# 🐷✋ 肘子播放器

基于 mpv + GTK4 的桌面音乐播放器，原生 GNOME 风格，支持 MPRIS 媒体控件。

## 截图

![肘子播放器](zhouzi-player.svg)

## 功能

- 🎵 播放本地音乐（mp3 / flac / m4a / ogg / wav ...）
- 🔍 实时搜索过滤播放列表
- 🎲 随机播放模式
- 🎚️ 进度条拖拽、键盘快捷键（空格/左右方向键）
- 🎛️ GNOME 媒体控件（MPRIS D-Bus 集成）
- 🎨 专辑封面提取和显示
- 🔔 桌面通知（歌曲切换时）

## 安装

### 一键安装

```bash
git clone <仓库地址>  # 或解压你收到的文件夹
cd reasonix
./install.sh
```

安装脚本会自动：
1. 安装系统依赖（mpv、ffmpeg、GTK4、libadwaita 等）
2. 安装 Python 依赖（mutagen）
3. 复制程序文件到 `~/.local/share/zhouzi-player/`
4. 注册桌面启动器
5. 安装应用图标
6. 添加 `zhouzi-player` 命令到 PATH

### 手动安装

```bash
# 安装依赖
sudo apt install mpv ffmpeg python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-notify-0.7 \
    python3-mutagen

# 运行
python3 player.py
```

## 使用

- **启动**：在应用列表中搜索「肘子播放器」，或在终端执行 `zhouzi-player`
- **添加音乐**：点击 ☰ 菜单 → **文件位置**，选择你的音乐文件夹
- **搜索**：在搜索框输入歌名/艺术家名过滤列表
- **快进/快退**：左右方向键（±5 秒）
- **播放/暂停**：空格键

## 卸载

```bash
rm -rf ~/.local/share/zhouzi-player
rm -f ~/.local/share/applications/zhouzi-player.desktop
rm -f ~/.local/share/icons/hicolor/128x128/apps/zhouzi-player.svg
rm -f ~/.local/bin/zhouzi-player
```

## 技术栈

- **Python 3** + **PyGObject** (GTK 4 + libadwaita)
- **mpv** 作为播放后端（IPC socket 通信）
- **ffmpeg** 专辑封面提取
- **mutagen** 音频元数据解析
- **MPRIS D-Bus** GNOME 媒体控件集成
