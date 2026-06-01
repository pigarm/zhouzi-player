# 🐞 肘子播放器 Bug 追踪

> 最后更新：2026-06-01
> 项目位置：`~/桌面/reasonix/`

---

## 状态说明

| 标记 | 含义 |
|------|------|
| ✅ **已修复** | 已定位并修改完成 |
| 🔴 **待修复** | 确定是 bug，需要修复 |
| 🟡 **需确认** | 疑似问题，但不确定是设计还是 bug |
| 🟢 **建议** | 非 bug，但值得改进 |

---

## ✅ 已修复

### #1 窗口图标不显示

- **文件**：`player.py`
- **位置**：`Player.__init__()`，原第 406–409 行
- **描述**：`self.set_icon_name("zhouzi-player")` 在 GTK4 中需要图标已注册到系统图标主题才能生效。直接运行 `player.py` 时图标未安装，调用无效。
- **修复**：
  - 新增 `_ensure_icon_installed()` 模块级函数（第 428–448 行）
  - 首次运行自动将 `zhouzi-player.svg` 复制到 `~/.local/share/icons/hicolor/scalable/apps/` 并执行 `gtk-update-icon-cache`
  - 后续启动检测到图标已存在则跳过
- **验证**：杀掉进程重新启动，窗口标题栏/任务栏应显示小猪图标

### #5 MPRIS 元数据与 UI 显示不一致

- **文件**：`player.py`
- **位置**：`Mpris._meta()` 原第 287–307 行；`Player._format_display()` 原第 714–764 行
- **描述**：MPRIS 的 `_meta()` 直接用文件名做启发式切割（`文件名.split(" - ")`）来猜测歌手/标题，而 UI 用 mutagen 读取 ID3 标签。结果是 GNOME 媒体控件显示的歌曲信息跟播放器界面不同。
- **修复**：
  - 新增 `_read_metadata(path)` 模块级函数（第 407–426 行），统一用 mutagen 读取 `{title, artist, album}`
  - `_format_display()` 和 `_meta()` 都调用此函数，保证数据源一致
  - MPRIS 新增 `xesam:album` 字段（原来缺失）
  - MPRIS 的 `xesam:title` 从原来的 `文件名.mp3` 改为 `Path(p).stem`（去掉扩展名），有标签时用真正的歌名

---

## 🔴 待修复

### #2 `_add_dir()` 死代码

- **文件**：`player.py`
- **位置**：`Player._add_dir()` 第 ~660 行
- **描述**：`_add_dir()` 实现了完整的"选择文件夹并增量扫描"功能，但没有任何按钮或菜单项连接到它。设置菜单里用的是 `_on_settings_folder`（清空列表重扫），所以这个方法是死代码。
- **影响**：不影响运行，但造成代码冗余。如果有"新增文件夹到当前列表"的需求，需要把 `_add_dir` 挂到 UI 上。
- **建议修复**：
  - 给菜单加个"添加音乐文件夹"按钮，绑定 `_add_dir`
  - 或删除死代码（如果不需要增量添加功能）

### #3 `_format_display()` 文件名 fallback 歧义

- **文件**：`player.py`
- **位置**：`Player._format_display()` fallback 分支
- **描述**：文件名启发式假定格式为 `艺术家 - 标题.ext`，然后交换成 `标题 - 艺术家.ext`。但如果文件名是 `周杰伦 - 七里香 - 专辑版.mp3`，会切成 `first="周杰伦"`, `rest="七里香 - 专辑版.mp3"`，输出变成 `七里香 - 专辑版 - 周杰伦.mp3`，把专辑名当标题了。
- **影响**：当音频文件**没有 ID3 标签**且文件名包含多个 ` - ` 时，显示名称会混乱。
- **建议修复**：
  - 文件名 fallback 只对 `艺术家 - 标题.ext`（恰好一个 ` - `）的格式做交换
  - 多于一个 ` - ` 时直接用原始文件名，不做启发式

### #4 切换文件夹不清理 `_fmt_cache`

- **文件**：`player.py`
- **位置**：`Player._format_display()` 类级缓存 `Player._fmt_cache`
- **描述**：`Player._fmt_cache` 是类级别的静态字典，切换音乐文件夹后（`_on_settings_folder_done`）不清空。旧文件夹的文件名映射一直占用内存。
- **影响**：对大多数用户无实际影响（内存增加可忽略）。但如果频繁切换大目录，缓存会持续膨胀。
- **建议修复**：在 `_on_settings_folder_done()` 清空列表的地方加一句 `Player._fmt_cache.clear()`

---

## 🟡 需确认

### #8 `_next()` 和 `_prev()` 行为相同

- **文件**：`player.py`
- **位置**：`Player._next()` 和 `Player._prev()` 第 ~610–620 行
- **描述**：上下曲切换都调用 `random.randrange()` 随机选歌，没有顺序播放的"下一首/上一首"概念。
- **判断**：如果这是有意设计的**纯随机播放模式**，则不是 bug。但按钮图标（`media-skip-backward/forward-symbolic`）暗示的是顺序跳转，用户体验上可能会有违和感。
- **建议**：如果确定要坚持纯随机，改按钮 tooltip 为"随机下一首"会更清晰。如果想加播放模式切换（顺序/随机/单曲循环），需要增加 `_play_mode` 状态变量。

---

## 🟢 建议改进

### #6 大目录扫描卡 UI

- **文件**：`player.py`
- **位置**：`Player._scan()` 第 ~670 行
- **描述**：`_scan()` 使用 `os.walk()` 全量扫描目录，跑在 GTK 主线程上。几千首歌的文件夹会导致界面卡死几秒甚至十几秒。
- **建议**：
  - 用 `GLib.idle_add()` 分批添加文件，每次 idle 回调加几十个
  - 或开一个后台线程扫描，完成后再通过 `GLib.idle_add()` 更新 UI

### #7 `_command()` 解码风险

- **文件**：`player.py`
- **位置**：`MpvControl._command()` 第 162 行
- **描述**：`r.decode().strip()` 如果 mpv 返回不完整 UTF-8 序列，会抛 `UnicodeDecodeError`。外层 `except: pass` 吞掉异常后返回 `None`，导致静默失败。
- **建议**：改为 `r.decode("utf-8", errors="replace")`，用替换字符代替崩溃。

### #9 `_list_act` O(n) 匹配

- **文件**：`player.py`
- **位置**：`Player._list_act()` 第 ~690 行
- **描述**：点击列表项时遍历所有文件查找匹配的显示名。可以建一个 `dict[显示名, 索引]` 反向映射实现 O(1) 查找。
- **影响**：几百首歌无感，几千首时才有可见延迟。

### #10 大量 `except: pass`

- **文件**：`player.py`
- **位置**：多处（`_command`, `_poll`, `_format_display`, `_meta` 等）
- **描述**：大量使用裸 `except: pass`，异常被完全静默。调试困难。
- **建议**：加日志输出到 stderr，至少 `import sys; print(f"[ERROR] ...", file=sys.stderr)`。

---

## 文件列表

| 文件 | 行数 | 说明 |
|------|------|------|
| `player.py` | 968 | 主程序 |
| `install.sh` | 75 | 一键安装脚本 |
| `build-deb.sh` | - | deb 打包脚本 |
| `zhouzi-player.svg` | - | 应用图标 |
| `zhouzi.player.desktop` | - | 桌面启动器模板 |
| `README.md` | - | 项目说明 |
| `zhouzi-player_1.0.0_all.deb` | - | 已打包的 deb |
