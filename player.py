#!/usr/bin/env python3
"""肘子播放器 — GTK 4 + libadwaita + MPRIS GNOME 原生版"""

import json
import os
import socket
import subprocess
import time
from pathlib import Path
import sys
import threading
import random

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Notify", "0.7")
from gi.repository import GLib, Gtk, Adw, Gdk, Gio, Pango, Notify, GObject

SOCKET_PATH = "/tmp/mpv-music-player.sock"
CONFIG_DIR = Path.home() / ".config" / "zhouzi-player"
CONFIG_FILE = CONFIG_DIR / "config.json"
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma"}
NOTIFY_NAME = "肘子播放器"
NOTIFY_ICON = "audio-x-generic"
MPRIS_NAME = "org.mpris.MediaPlayer2.zhouzi_player"
MPRIS_PATH = "/org/mpris/MediaPlayer2"

MPRIS_XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/><method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/><method name="Previous"/>
    <method name="Pause"/><method name="PlayPause"/>
    <method name="Stop"/><method name="Play"/>
    <method name="Seek"><arg name="Offset" type="x" direction="in"/></method>
    <method name="SetPosition"><arg name="TrackId" type="o" direction="in"/><arg name="Position" type="x" direction="in"/></method>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="read"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
    <signal name="Seeked"><arg name="Position" type="x" direction="out"/></signal>
  </interface>
</node>
"""


# ─────────────────────────────────────────────────────────────
#  工具函数：确定性封面缓存名（避免 Python hash 随机化导致重复缓存）
# ─────────────────────────────────────────────────────────────

def _cover_stem(path: str) -> str:
    """返回文件路径的确定性哈希，用作封面缓存文件名"""
    import hashlib
    return hashlib.md5(path.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────
#  mpv IPC
# ─────────────────────────────────────────────────────────────

class MpvControl:
    def __init__(self):
        self.proc: subprocess.Popen | None = None

    def start(self):
        # 先停掉已有的 mpv 进程（防止前端崩溃后残留后台播放）
        self._kill_existing()
        self._cleanup_socket()
        self.proc = subprocess.Popen(
            ["mpv", "--no-video", "--idle=yes",
             f"--input-ipc-server={SOCKET_PATH}",
             "--audio-display=no", "--terminal=no"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(30):
            if os.path.exists(SOCKET_PATH): return
            time.sleep(0.1)
        raise RuntimeError("mpv 启动超时")

    def _kill_existing(self):
        """通过 socket 或 pkill 终止已有的 mpv 实例"""
        # 1) 尝试通过 IPC socket 发送 quit
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(SOCKET_PATH)
            s.sendall((json.dumps({"command": ["quit"]}) + "\n").encode())
            s.close()
            time.sleep(0.3)
        except Exception:
            pass
        # 2) 备用：pkill 匹配我们启动的 mpv 进程
        try:
            subprocess.run(
                ["pkill", "-f", f"mpv.*--input-ipc-server={SOCKET_PATH}"],
                capture_output=True, timeout=3,
            )
        except Exception:
            pass
        time.sleep(0.2)

    def stop(self):
        self._command("quit")
        if self.proc:
            try: self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired: self.proc.kill()
            self.proc = None
        self._cleanup_socket()

    def load(self, p): self._command("loadfile", p)
    def append(self, p): self._command("loadfile", p, "append")
    def play_pause(self):
        p = self.get_property("pause")
        self._command("set", "pause", "no" if p else "yes")
    def stop_playback(self): self._command("stop")
    def seek(self, s): self._command("seek", str(s), "absolute")
    def seek_rel(self, s): self._command("seek", str(s), "relative+exact")
    def set_vol(self, v): self._command("set", "volume", str(max(0, min(100, v))))

    def get_property(self, name):
        try:
            r = self._command("get_property", name)
            if r: return json.loads(r).get("data")
        except: pass
        return None

    def _command(self, *args):
        if not os.path.exists(SOCKET_PATH): return None
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2); s.connect(SOCKET_PATH)
            s.sendall((json.dumps({"command": list(args)}) + "\n").encode())
            r = b""
            while True:
                c = s.recv(4096)
                if not c: break
                r += c
                if c.endswith(b"\n"): break
            s.close()
            return r.decode().strip()
        except: return None

    @staticmethod
    def _cleanup_socket():
        try: os.unlink(SOCKET_PATH)
        except FileNotFoundError: pass


# ─────────────────────────────────────────────────────────────
#  MPRIS D-Bus
# ─────────────────────────────────────────────────────────────

class Mpris:
    """在 session bus 上注册 MPRIS 接口，让 GNOME 显示常驻媒体控件"""

    def __init__(self):
        self.conn: Gio.DBusConnection | None = None
        self.reg_ids: list[int] = []
        self.owner_id: int | None = None
        self.node = Gio.DBusNodeInfo.new_for_xml(MPRIS_XML)
        self.window: "Player" | None = None

    def start(self):
        self.owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION, MPRIS_NAME,
            Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT
            | Gio.BusNameOwnerFlags.REPLACE,
            self._on_bus,    # bus_acquired
            None,             # name_acquired (unused)
            None,             # name_lost (unused)
        )

    def _on_bus(self, conn: Gio.DBusConnection, _name: str):
        """总线连接已就绪 → 注册对象"""
        self.conn = conn
        self.reg_ids = []
        for iface in self.node.interfaces:
            rid = conn.register_object(
                MPRIS_PATH, iface,
                self._call, self._get, self._set,
            )
            self.reg_ids.append(rid)
        print(f"[MPRIS] ✓ 注册完成: {MPRIS_NAME}", file=sys.stderr)

    def stop(self):
        if self.owner_id:
            Gio.bus_unown_name(self.owner_id)
            self.owner_id = None
        if self.reg_ids and self.conn:
            for rid in self.reg_ids:
                try: self.conn.unregister_object(rid)
                except: pass

    def emit(self, props: dict):
        """发送 PropertiesChanged 信号"""
        if not self.conn: return
        try:
            self.conn.emit_signal(
                None, MPRIS_PATH,
                "org.freedesktop.DBus.Properties", "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.mpris.MediaPlayer2.Player", props, [])),
            )
        except: pass

    # ── 属性读取 ──

    def _status(self):
        w = self.window
        if not w or not w.mpv.get_property("path"): return "Stopped"
        return "Paused" if w.mpv.get_property("pause") else "Playing"

    _cover_cache: dict[str, str] = {}
    _cover_semaphore = threading.Semaphore(3)  # 最多 3 个 ffmpeg 同时跑

    def _extract_cover(self, path: str) -> str | None:
        """从音频文件提取专辑封面，返回 file:// URL"""
        if path in self._cover_cache:
            c = self._cover_cache[path]
            return c if c else None

        cover_dir = Path.home() / ".cache" / "zhouzi-player" / "covers"
        cover_dir.mkdir(parents=True, exist_ok=True)
        stem = _cover_stem(path)
        cover_jpg = cover_dir / f"{stem}.jpg"
        cover_png = cover_dir / f"{stem}.png"

        # 检查本地缓存是否已有
        if cover_jpg.exists():
            self._cover_cache[path] = f"file://{cover_jpg}"
            return self._cover_cache[path]
        if cover_png.exists():
            self._cover_cache[path] = f"file://{cover_png}"
            return self._cover_cache[path]

        # ffmpeg 提取封面（限并发）
        self._cover_semaphore.acquire()
        try:
            subprocess.run(
                ["ffmpeg", "-i", path, "-an", "-vcodec", "copy",
                 str(cover_jpg), "-y", "-loglevel", "quiet"],
                timeout=10,
            )
            if cover_jpg.exists() and cover_jpg.stat().st_size > 500:
                self._cover_cache[path] = f"file://{cover_jpg}"
                return self._cover_cache[path]

            # 也可能是 png
            subprocess.run(
                ["ffmpeg", "-i", path, "-an", "-vcodec", "copy",
                 str(cover_png), "-y", "-loglevel", "quiet"],
                timeout=10,
            )
            if cover_png.exists() and cover_png.stat().st_size > 500:
                self._cover_cache[path] = f"file://{cover_png}"
                return self._cover_cache[path]
        except Exception:
            pass
        finally:
            self._cover_semaphore.release()

        self._cover_cache[path] = ""
        return None

    def _meta(self):
        w = self.window
        if not w:
            return GLib.Variant("a{sv}", {})
        p = w.mpv.get_property("path")
        if not p:
            return GLib.Variant("a{sv}", {})
        d = w.mpv.get_property("duration") or 0
        meta = _read_metadata(p)
        title = meta["title"] or Path(p).stem
        artist = meta["artist"]
        album = meta["album"]
        m = {
            "mpris:trackid": GLib.Variant("o", f"{MPRIS_PATH}/Track/1"),
            "mpris:length": GLib.Variant("x", int(float(d) * 1_000_000)),
            "xesam:title": GLib.Variant("s", title),
            "xesam:url": GLib.Variant("s", f"file://{p}"),
        }
        if artist:
            m["xesam:artist"] = GLib.Variant("as", [artist])
        if album:
            m["xesam:album"] = GLib.Variant("s", album)
        # 专辑封面
        art = self._extract_cover(p)
        if art:
            m["mpris:artUrl"] = GLib.Variant("s", art)
        return GLib.Variant("a{sv}", m)

    def _pos(self):
        p = self.window.mpv.get_property("time-pos") if self.window else 0
        return int(float(p or 0) * 1_000_000)

    # ── D-Bus 回调 ──

    def _call(self, _c, _s, _p, iface, method, params, inv):
        w = self.window
        if not w: return
        m = w.mpv
        if iface == "org.mpris.MediaPlayer2":
            if method == "Raise": w.present()
            elif method == "Quit": w.do_close_request()
            inv.return_value(None)
            return
        if iface == "org.mpris.MediaPlayer2.Player":
            if method == "Next":
                w._skip_notif = True; w._next()
            elif method == "Previous":
                w._skip_notif = True; w._prev()
            elif method == "PlayPause": w._play_pause()
            elif method == "Play":
                if m.get_property("pause"): m.play_pause()
            elif method == "Pause":
                if not m.get_property("pause"): m.play_pause()
            elif method == "Stop": w._on_stop()
            elif method == "Seek":
                off = params.unpack()[0]
                m.seek_rel(off / 1_000_000)
                self._seeked()
            elif method == "SetPosition":
                _, pos = params.unpack()
                m.seek(pos / 1_000_000)
                self._seeked()
            inv.return_value(None)

    def _get(self, _c, _s, _p, iface, prop):
        w = self.window
        m = w.mpv if w else None
        has = bool(m and m.get_property("path"))
        if iface == "org.mpris.MediaPlayer2":
            tbl = {
                "CanQuit": GLib.Variant("b", True),
                "CanRaise": GLib.Variant("b", True),
                "HasTrackList": GLib.Variant("b", False),
                "Identity": GLib.Variant("s", NOTIFY_NAME),
                "DesktopEntry": GLib.Variant("s", "zhouzi-player"),
                "SupportedUriSchemes": GLib.Variant("as", ["file"]),
                "SupportedMimeTypes": GLib.Variant("as", list(AUDIO_EXTS)),
            }
            return tbl.get(prop)
        if iface == "org.mpris.MediaPlayer2.Player":
            tbl = {
                "PlaybackStatus": GLib.Variant("s", self._status()),
                "LoopStatus": GLib.Variant("s", "None"),
                "Rate": GLib.Variant("d", 1.0),
                "Shuffle": GLib.Variant("b", False),
                "Metadata": self._meta(),
                "Volume": GLib.Variant("d", m.get_property("volume") or 0.0 if m else 0.0),
                "Position": GLib.Variant("x", self._pos()),
                "MinimumRate": GLib.Variant("d", 1.0),
                "MaximumRate": GLib.Variant("d", 1.0),
                "CanGoNext": GLib.Variant("b", has),
                "CanGoPrevious": GLib.Variant("b", has),
                "CanPlay": GLib.Variant("b", True),
                "CanPause": GLib.Variant("b", True),
                "CanSeek": GLib.Variant("b", True),
                "CanControl": GLib.Variant("b", True),
            }
            return tbl.get(prop)
        return None

    def _set(self, _c, _s, _p, iface, prop, val):
        w = self.window
        if iface == "org.mpris.MediaPlayer2.Player" and prop == "Volume":
            w.mpv.set_vol(int(val.get_double()))
            return True
        return False

    def _seeked(self):
        if not self.conn: return
        try:
            self.conn.emit_signal(None, MPRIS_PATH,
                "org.mpris.MediaPlayer2.Player", "Seeked",
                GLib.Variant("(x)", (self._pos(),)))
        except: pass


# ─────────────────────────────────────────────────────────────
#  共享工具函数
# ─────────────────────────────────────────────────────────────

def _read_metadata(path: str) -> dict:
    """读取音频文件元数据，返回 {title, artist, album}，缺失的字段为 None"""
    try:
        from mutagen import File as MFile
        f = MFile(path)
        if f is not None and f.tags:
            def _safe_tag(key):
                v = f.get(key)
                if v is None:
                    return None
                if isinstance(v, list):
                    return str(v[0]).strip()
                if hasattr(v, 'text'):
                    return str(v.text[0]).strip()
                return str(v).strip()
            return {
                "title": _safe_tag('TIT2') or _safe_tag('title'),
                "artist": _safe_tag('TPE1') or _safe_tag('artist'),
                "album": _safe_tag('TALB') or _safe_tag('album'),
            }
    except Exception:
        pass
    return {"title": None, "artist": None, "album": None}


def _ensure_icon_installed():
    """将 SVG 图标安装到用户图标主题，让 set_icon_name 生效"""
    src = Path(__file__).parent / "zhouzi-player.svg"
    if not src.exists():
        return
    dest = Path.home() / ".local/share/icons/hicolor/scalable/apps/zhouzi-player.svg"
    if dest.exists():
        return  # 已安装
    dest.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(str(src), str(dest))
    # 刷新图标缓存
    import subprocess
    cache_dir = Path.home() / ".local/share/icons/hicolor"
    subprocess.run(
        ["gtk-update-icon-cache", str(cache_dir)],
        capture_output=True, timeout=10,
    )


# ─────────────────────────────────────────────────────────────
#  GTK 界面
# ─────────────────────────────────────────────────────────────

class Player(Adw.ApplicationWindow):
    def __init__(self, mpris: Mpris, **kw):
        super().__init__(**kw)
        self.set_title(NOTIFY_NAME)
        self.set_default_size(520, 520)
        # 设置窗口图标 — 如果是首次运行会自安装到用户图标主题
        _ensure_icon_installed()
        self.set_icon_name("zhouzi-player")

        self.mpv = MpvControl()
        self.mpris = mpris
        mpris.window = self

        self._files: list[str] = []
        self._store = Gtk.StringList.new([])
        self._idx: int | None = None
        self._last_idx: int | None = None
        self._seeking = False
        self._last_song = ""
        self._notif: Notify.Notification | None = None
        self._skip_notif = False  # MPRIS 控制时跳过通知

        self._build()
        self._keys()

        self.mpv.start()
        self._load_last()
        GLib.timeout_add(400, self._poll)

    # ── 配置 ──

    def _load_cfg(self) -> dict:
        try:
            if CONFIG_FILE.exists(): return json.loads(CONFIG_FILE.read_text())
        except: pass
        return {}

    def _save_cfg(self, d: dict):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False))
        except: pass

    def _load_last(self):
        c = self._load_cfg()
        f = c.get("last_folder", "")
        if f and os.path.isdir(f): self._scan(f, play=False)

    def _save_last(self, f: str):
        c = self._load_cfg(); c["last_folder"] = f; self._save_cfg(c)

    # ── 界面 ──

    def _build(self):
        tv = Adw.ToolbarView(); self.set_content(tv)
        h = Adw.HeaderBar(); tv.add_top_bar(h)

        self.b_prev = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        self.b_prev.set_tooltip_text("上一首"); self.b_prev.connect("clicked", lambda _: self._prev())
        h.pack_start(self.b_prev)

        self.b_play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.b_play.set_tooltip_text("播放/暂停"); self.b_play.connect("clicked", lambda _: self._play_pause())
        h.pack_start(self.b_play)

        self.b_next = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        self.b_next.set_tooltip_text("下一首"); self.b_next.connect("clicked", lambda _: self._next())
        h.pack_start(self.b_next)

        self.b_stop = Gtk.Button.new_from_icon_name("media-playback-stop-symbolic")
        self.b_stop.set_tooltip_text("停止"); self.b_stop.connect("clicked", lambda _: self._on_stop())
        h.pack_start(self.b_stop)

        # ── 设置按钮 ──
        self.b_settings = Gtk.MenuButton.new()
        self.b_settings.set_icon_name("open-menu-symbolic")
        self.b_settings.set_tooltip_text("设置")

        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        popover_box.set_margin_top(6); popover_box.set_margin_bottom(6)
        popover_box.set_margin_start(12); popover_box.set_margin_end(12)

        # 文件位置设置
        loc_btn = Gtk.Button.new_with_label("📁 文件位置设置")
        loc_btn.set_halign(Gtk.Align.START)
        loc_btn.add_css_class("flat")
        loc_btn.connect("clicked", self._on_settings_folder)
        popover_box.append(loc_btn)

        # 分隔线
        sep = Gtk.Separator.new(Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(4); sep.set_margin_bottom(4)
        popover_box.append(sep)

        self._settings_popover = Gtk.Popover.new()
        self._settings_popover.set_child(popover_box)
        self.b_settings.set_popover(self._settings_popover)
        h.pack_end(self.b_settings)

        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        c.set_margin_top(12); c.set_margin_bottom(12); c.set_margin_start(12); c.set_margin_end(12)
        tv.set_content(c)

        self.time_l = Gtk.Label(label="00:00 / 00:00"); c.append(self.time_l)

        self.prog = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.5)
        self.prog.set_draw_value(False); self.prog.set_hexpand(True)
        self.prog.connect("change-value", self._seek)
        c.append(self.prog)


        self.song_l = Gtk.Label(label="没有播放")
        self.song_l.set_ellipsize(Pango.EllipsizeMode.END)
        self.song_l.set_margin_top(4); self.song_l.add_css_class("dim-label")
        c.append(self.song_l)

        # ── 搜索框 ──
        self.search_entry = Gtk.SearchEntry.new()
        self.search_entry.set_placeholder_text("搜索歌曲 / 专辑 / 作者…")
        self.search_entry.set_margin_top(8)
        self.search_entry.connect("search-changed", self._on_search)
        self.search_entry.connect("stop-search", self._on_search_clear)
        c.append(self.search_entry)

        lh = Gtk.Label(label="播放列表")
        lh.set_halign(Gtk.Align.START); lh.set_margin_top(4); lh.add_css_class("heading")
        c.append(lh)

        # 过滤模型链: StringList → FilterListModel → SingleSelection → ListView
        self._filter_model = Gtk.FilterListModel.new(self._store)
        self._custom_filter = Gtk.CustomFilter.new(self._filter_func, None)
        self._filter_model.set_filter(self._custom_filter)

        sel = Gtk.SingleSelection.new(self._filter_model)
        fac = Gtk.SignalListItemFactory()
        fac.connect("setup", self._item_setup); fac.connect("bind", self._item_bind)
        self.lv = Gtk.ListView.new(sel, fac); self.lv.set_vexpand(True)
        self.lv.connect("activate", self._list_act)
        sw = Gtk.ScrolledWindow(); sw.set_vexpand(True); sw.set_child(self.lv)
        c.append(sw)

    def _keys(self):
        c = Gtk.EventControllerKey.new()
        c.connect("key-pressed", self._key)
        self.add_controller(c)

    def _key(self, _c, k, _kc, _s):
        if k == Gdk.KEY_space: self._play_pause(); return True
        if k == Gdk.KEY_Left: self.mpv.seek_rel(-5); return True
        if k == Gdk.KEY_Right: self.mpv.seek_rel(5); return True

        return False

    # ── 控制 ──

    def _play_pause(self):
        if not self._files: self._add_file(); return
        # 停止后点播放 → 恢复最后播放的歌曲
        if self._idx is None and self._last_idx is not None:
            self._play(self._last_idx)
            return
        self.mpv.play_pause()

    def _on_stop(self):
        self.mpv.stop_playback()
        self._idx = None
        self.song_l.set_text("已停止")
        self._last_song = ""; self._close_notif()

    def _next(self):
        if self._idx is None or not self._files: return
        nxt = random.randrange(len(self._files))
        while nxt == self._idx and len(self._files) > 1:
            nxt = random.randrange(len(self._files))
        self._play(nxt)

    def _prev(self):
        if self._idx is None or not self._files: return
        nxt = random.randrange(len(self._files))
        while nxt == self._idx and len(self._files) > 1:
            nxt = random.randrange(len(self._files))
        self._play(nxt)

    def _play(self, i):
        if 0 <= i < len(self._files):
            self._idx = i; self._last_idx = i
            self.mpv.load(self._files[i])
            self.mpv._command("set", "pause", "no")  # 强制播放
            # 在过滤后的列表中找到对应行并选中
            fidx = self._find_filtered_idx(i)
            if fidx is not None:
                self.lv.get_model().set_selected(fidx)

    # ── 文件 ──

    def _add_file(self, *a):
        d = Gtk.FileDialog.new(); d.set_title("选择音乐文件")
        c = self._load_cfg(); last = c.get("last_folder", "")
        if last and os.path.isdir(last): d.set_initial_folder(Gio.File.new_for_path(last))
        f = Gtk.FileFilter(); f.set_name("音频文件")
        for e in ("*.mp3", "*.wav", "*.flac", "*.ogg", "*.m4a", "*.aac"): f.add_pattern(e)
        d.set_default_filter(f); d.open_multiple(self, None, self._on_files)

    def _on_files(self, d, r):
        try:
            fs = d.open_multiple_finish(r)
            if fs: self._save_last(str(Path(fs[0].get_path()).parent))
        except GLib.GError: return
        new_paths = []
        for g in fs:
            p = g.get_path()
            if p not in self._files:
                new_paths.append(p)
        if new_paths:
            new_paths.sort(key=lambda p: Player._format_display(p).lower())
            for p in new_paths:
                self._files.append(p); self._store.append(self._format_display(p))
                if self._idx is None: self._play(len(self._files) - 1)

    def _add_dir(self, *a):
        d = Gtk.FileDialog.new(); d.set_title("选择音乐文件夹")
        c = self._load_cfg(); last = c.get("last_folder", "")
        if last and os.path.isdir(last): d.set_initial_folder(Gio.File.new_for_path(last))
        d.select_folder(self, None, self._on_dir)

    def _on_dir(self, d, r):
        try: f = d.select_folder_finish(r)
        except GLib.GError: return
        self._save_last(f.get_path()); self._scan(f.get_path())

    def _scan(self, fp, play=True):
        new_files = []
        for r, _, fs in os.walk(fp):
            for f in sorted(fs):
                if Path(f).suffix.lower() in AUDIO_EXTS:
                    p = os.path.join(r, f)
                    if p not in self._files:
                        new_files.append(p)
        new_files.sort(key=lambda p: Player._format_display(p).lower())
        for p in new_files:
            self._files.append(p); self._store.append(self._format_display(p))
        n = len(new_files)
        if n == 0: self.song_l.set_text("没有找到音乐文件")
        else:
            self.song_l.set_text(f"已添加 {n} 首歌")
            if play and self._idx is None: self._play(0)

    def _list_act(self, _v, filtered_pos):
        """列表点击：将过滤后的位置映射回 _files 索引后播放"""
        if filtered_pos == Gtk.INVALID_LIST_POSITION:
            return
        item = self._filter_model.get_item(filtered_pos)
        display = item.get_string()
        for i, path in enumerate(self._files):
            if self._format_display(path) == display:
                self._play(i)
                break

    # ── 搜索过滤 ──

    def _filter_func(self, item, _user_data):
        """自定义过滤器：检查条目是否匹配搜索文本（不区分大小写）"""
        query = self.search_entry.get_text().strip().lower()
        if not query:
            return True  # 无搜索词时显示全部
        display = item.get_string().lower()
        return query in display

    def _on_search(self, _entry):
        """搜索文本变化 → 通知过滤器重新评估"""
        self._custom_filter.changed(Gtk.FilterChange.DIFFERENT)
        # 如果当前正在播放，尝试保持选中
        if self._idx is not None:
            fidx = self._find_filtered_idx(self._idx)
            if fidx is not None:
                self.lv.get_model().set_selected(fidx)

    def _on_search_clear(self, _entry):
        """搜索框清空（Esc / 清除按钮）"""
        self.search_entry.set_text("")

    def _find_filtered_idx(self, unfiltered_idx: int) -> int | None:
        """将 _files 原始索引转换为过滤模型中的位置"""
        if unfiltered_idx is None or unfiltered_idx >= len(self._files):
            return None
        display = self._format_display(self._files[unfiltered_idx])
        n = self._filter_model.get_n_items()
        for i in range(n):
            item = self._filter_model.get_item(i)
            if item.get_string() == display:
                return i
        return None

    def _item_setup(self, _f, item):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_start(4); box.set_margin_end(8)
        box.set_margin_top(2); box.set_margin_bottom(2)

        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(label)

        item.set_child(box)

    def _item_bind(self, _f, item):
        box = item.get_child()
        label = box.get_first_child()
        title = item.get_item().get_string()
        label.set_text(title)

    @staticmethod
    def _format_display(path: str) -> str:
        """从音频元数据读取「标题 - 艺术家」，一致显示；无元数据时回退到文件名格式"""
        # 简单缓存，避免同一文件反复读取
        if not hasattr(Player, "_fmt_cache"):
            Player._fmt_cache: dict[str, str] = {}
        cached = Player._fmt_cache.get(path)
        if cached:
            return cached

        meta = _read_metadata(path)
        title, artist, album = meta["title"], meta["artist"], meta["album"]
        if title and artist:
            if album:
                result = f"{title} - {album} - {artist}"
            else:
                result = f"{title} - {artist}"
            Player._fmt_cache[path] = result
            return result

        # 回退：文件名启发式，交换 "艺术家-标题" → "标题-艺术家"
        name = Path(path).name
        parts = name.split(" - ", 1)
        if len(parts) > 1:
            first, rest = parts[0], parts[1]
            dot = rest.rfind(".")
            if dot > 0:
                result = f"{rest[:dot]} - {first}{rest[dot:]}"
            else:
                result = f"{rest} - {first}"
        else:
            result = name
        Player._fmt_cache[path] = result
        return result

    def _seek(self, _s, _t, v):
        if self._seeking: return
        d = self.mpv.get_property("duration")
        if d and float(d) > 0: self.mpv.seek(float(v) / 100 * float(d))



    # ── 通知 ──

    def _notif_cb(self, _n, action, _u):
        if action == "play-pause": self._play_pause(); GLib.timeout_add(200, self._refresh_n)
        elif action == "next": self._next(); GLib.timeout_add(200, self._refresh_n)
        elif action == "prev": self._prev()
        elif action == "default": self.present()

    def _show_n(self, name):
        self._close_notif()
        # 如果有封面图，用作通知图标
        icon = NOTIFY_ICON  # 默认图标
        cover_url = self.mpris._extract_cover(
            self.mpv.get_property("path") or ""
        )
        if cover_url:
            icon = cover_url.replace("file://", "")
        n = Notify.Notification.new(name, NOTIFY_NAME, icon)
        paused = self.mpv.get_property("pause")
        pt = "▶ 播放" if paused else "⏸ 暂停"
        n.add_action("default", "打开播放器", self._notif_cb, None)
        n.add_action("play-pause", pt, self._notif_cb, None)
        n.add_action("next", "⏭ 下一首", self._notif_cb, None)
        n.add_action("prev", "⏮ 上一首", self._notif_cb, None)
        n.set_timeout(5000); n.set_urgency(Notify.Urgency.NORMAL); n.show()
        self._notif = n
        # 横幅消失后彻底清除通知，避免通知栏残留和 dock 红点
        # 记住当前通知对象，防止切歌时超时误关新通知
        def _delayed_close():
            if self._notif is n:
                self._close_notif()
            return False
        GLib.timeout_add(5500, _delayed_close)

    def _refresh_n(self):
        if self._last_song: self._show_n(self._last_song)
        return False

    def _close_notif(self):
        if self._notif:
            try: self._notif.close()
            except: pass
            self._notif = None

    # ── 设置回调 ──

    def _on_settings_folder(self, btn):
        """设置默认音乐文件夹"""
        d = Gtk.FileDialog.new(); d.set_title("选择默认音乐文件夹")
        c = self._load_cfg(); last = c.get("last_folder", "")
        if last and os.path.isdir(last): d.set_initial_folder(Gio.File.new_for_path(last))
        d.select_folder(self, None, self._on_settings_folder_done)
        self._settings_popover.popdown()

    def _on_settings_folder_done(self, d, r):
        try: f = d.select_folder_finish(r)
        except GLib.GError: return
        self._save_last(f.get_path())
        # 清空当前列表并加载新文件夹
        self._files.clear()
        self._store.remove(0, self._store.get_n_items())
        self._idx = None
        self._scan(f.get_path())

    # ── 轮询 ──

    def _poll(self):
        try:
            p = self.mpv.get_property("path")
            ps = self.mpv.get_property("pause")
            pos = self.mpv.get_property("time-pos")
            dur = self.mpv.get_property("duration")

            if p:
                n = Path(p).name
                new = n != self._last_song

                if new:
                    self._last_song = n
                    if self._skip_notif:
                        self._skip_notif = False
                    else:
                        self._show_n(n)
                    if p in self._files:
                        i = self._files.index(p)
                        if i != self._idx:
                            self._idx = i
                            fidx = self._find_filtered_idx(i)
                            if fidx is not None:
                                self.lv.get_model().set_selected(fidx)

                self.song_l.set_text(n); self.song_l.remove_css_class("dim-label")
                self.b_play.set_icon_name(
                    "media-playback-start-symbolic" if ps else "media-playback-pause-symbolic")

                if dur and pos and float(dur) > 0:
                    self._seeking = True; self.prog.set_value(float(pos)/float(dur)*100)
                    self._seeking = False
                    self.time_l.set_text(
                        f"{time.strftime('%M:%S', time.gmtime(int(float(pos))))} / "
                        f"{time.strftime('%M:%S', time.gmtime(int(float(dur))))}")

                # MPRIS 信号
                props = {
                    "PlaybackStatus": GLib.Variant("s", self.mpris._status()),
                    "CanGoNext": GLib.Variant("b", True),
                    "CanGoPrevious": GLib.Variant("b", True),
                    "CanPlay": GLib.Variant("b", True),
                    "CanPause": GLib.Variant("b", True),
                }
                if new:
                    props["Metadata"] = self.mpris._meta()
                self.mpris.emit(props)
            else:
                self.b_play.set_icon_name("media-playback-start-symbolic")
                if self._idx is not None and len(self._files) > 0:
                    nxt = random.randrange(len(self._files))
                    self._play(nxt)
                elif self._idx is not None:
                    self._idx = None; self.song_l.set_text("播放完毕")

                    # 停止时通知 MPRIS
                    self.mpris.emit({
                        "PlaybackStatus": GLib.Variant("s", "Stopped"),
                        "CanGoNext": GLib.Variant("b", False),
                        "CanGoPrevious": GLib.Variant("b", False),
                        "CanPlay": GLib.Variant("b", True),
                        "CanPause": GLib.Variant("b", False),
                    })
        except: pass
        return True

    # ── 关闭 ──

    def do_close_request(self):
        self.mpv.stop(); self.mpris.stop(); self._close_notif()
        return False


# ─────────────────────────────────────────────────────────────
#  Application
# ─────────────────────────────────────────────────────────────

class MusicApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="zhouzi.player")
        self.mpris = Mpris()
        self.window: Player | None = None
        Notify.init(NOTIFY_NAME)

    def do_activate(self):
        if not self.window:
            self.mpris.start()
            self.window = Player(self.mpris, application=self)
        self.window.present()


if __name__ == "__main__":
    MusicApp().run(sys.argv)
