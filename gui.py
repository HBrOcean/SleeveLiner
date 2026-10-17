#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SleeveLiner GUI —— 图形界面版

扁平设计：无渐变、无阴影，黑白灰主色 + 少量扁平功能色（成功绿 / 跳过橙 / 失败红）。
核心逻辑完全复用 sleeve_liner.py（CLI 与 GUI 共享同一套引擎）。

启动：
    python gui.py                 # 需要先 pip install PySide6
自测（无显示器的环境 / CI）：
    python gui.py --gui-selftest  # 构建界面 → 处理合成音频 → 截图退出
"""
import os
import sys
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

_BASE = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):          # PyInstaller 打包后与 exe 同目录
    _BASE = os.path.dirname(sys.executable)
sys.path.insert(0, _BASE)

import sleeve_liner as core                # noqa: E402  核心引擎

try:
    from PySide6.QtCore import Qt, QTimer, Signal, QObject, QUrl, QSettings
    from PySide6.QtGui import (QColor, QFont, QGuiApplication, QPainter, QPen,
                               QBrush, QPixmap, QDesktopServices, QKeySequence,
                               QShortcut, QPalette)
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                                   QHBoxLayout, QFrame, QLabel, QLineEdit,
                                   QListWidget, QListWidgetItem, QMainWindow,
                                   QPushButton,
                                   QSpinBox, QTextEdit, QVBoxLayout, QWidget,
                                   QFileDialog, QSizePolicy, QGridLayout)
except ImportError:
    print("[错误] 缺少 PySide6 库，请先安装：pip install PySide6-Essentials")
    sys.exit(1)

# ---------------------------------------------------------------------------
# 设计令牌（与品牌封面一致的黑白灰体系；功能色全部为纯色扁平）
# ---------------------------------------------------------------------------
BG     = "#F5F5F5"    # 窗口背景
SURF   = "#FFFFFF"    # 卡片 / 日志背景
INK    = "#111111"    # 主文字 / 主按钮
INK2   = "#555555"    # 次级文字
INK3   = "#999999"    # 弱文字
LINE   = "#DDDDDD"    # 常规边框
LINE2  = "#BBBBBB"    # 拖放虚线 / 强调边框
OK     = "#1E7E34"    # 成功（扁平绿）
WARN   = "#B26A00"    # 跳过（扁平橙）
ERR    = "#C22B2B"    # 失败（扁平红)

FONT_STACK = '"Noto Sans SC","Microsoft YaHei","PingFang SC","Segoe UI",sans-serif'
MONO_STACK = '"JetBrains Mono","Cascadia Mono","Consolas","Noto Sans Mono CJK SC",monospace'

QSS = f"""
* {{ font-family: {FONT_STACK}; font-size: 13px; color: {INK2}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}

/* ---------- 拖放区 ---------- */
QFrame#drop {{
    background: {SURF};
    border: 2px dashed #D4D4D4;
    border-radius: 10px;
}}
QFrame#drop[hover="true"] {{ border-color: {INK}; border-width: 2px; }}
QLabel#dropTitle {{ font-size: 16px; font-weight: 600; color: {INK}; background: transparent; }}
QLabel#dropHint  {{ font-size: 12px; color: #909090; background: transparent; }}
QLabel#dropCount {{ font-size: 13px; font-weight: 600; color: {INK}; background: transparent; }}

/* ---------- 选项卡片 ---------- */
QFrame#optCard {{
    background: {SURF};
    border: 1px solid {LINE};
    border-radius: 10px;
}}
QFrame#vline {{ background: {LINE}; border: none; }}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {SURF};
    border: 1px solid {LINE2};
    border-radius: 8px;
    padding: 5px 16px;
    min-height: 24px;
    color: {INK};
    font-weight: 500;
}}
QPushButton:hover  {{ background: #EAEAEA; }}
QPushButton:pressed{{ background: {LINE}; }}
QPushButton:disabled{{ background: {SURF}; color: {INK3}; border-color: {LINE}; }}

QPushButton#go {{
    background: {INK};
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 12px 24px;
    font-size: 15px;
    font-weight: 600;
}}
QPushButton#go:hover   {{ background: #333333; }}
QPushButton#go:pressed {{ background: #000000; }}
QPushButton#go:disabled{{ background: {LINE2}; color: {SURF}; }}

QPushButton#stop {{
    background: {SURF};
    color: {ERR};
    border: 1px solid {ERR};
    border-radius: 10px;
    padding: 12px 24px;
    font-size: 15px;
    font-weight: 600;
}}
QPushButton#stop:hover {{ background: #FBECEC; }}

/* ---------- 复选框 ---------- */
QCheckBox {{ spacing: 6px; color: {INK2}; background: transparent; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {LINE2};
    border-radius: 4px;
    background: {SURF};
}}
QCheckBox::indicator:hover   {{ border-color: {INK}; }}
QCheckBox::indicator:checked {{ background: {INK}; border-color: {INK}; }}

/* ---------- 输入控件（箭头用 Fusion 默认渲染，避免自绘异常） ---------- */
QSpinBox, QComboBox, QLineEdit {{
    background: {SURF};
    border: 1px solid {LINE2};
    border-radius: 8px;
    padding: 5px 8px;
    min-height: 22px;
    color: {INK};
}}
QSpinBox:hover, QComboBox:hover, QLineEdit:hover {{ border-color: {INK2}; }}
QSpinBox:focus, QComboBox:focus, QLineEdit:focus {{ border-color: {INK}; }}
QSpinBox {{ qproperty-alignment: AlignCenter; padding-right: 14px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {SURF};
    border: 1px solid {LINE2};
    selection-background-color: {INK};
    selection-color: #FFFFFF;
    outline: none;
}}

/* ---------- 进度 ---------- */
QLabel#statLabel {{ color: {INK2}; background: transparent; }}
QLabel#statFile  {{ color: {INK3}; background: transparent; font-size: 12px; }}

/* ---------- 日志 ---------- */
QTextEdit#log {{
    background: {SURF};
    border: 1px solid {LINE};
    border-radius: 10px;
    font-family: {MONO_STACK};
    font-size: 12px;
    color: {INK2};
    selection-background-color: {INK};
    selection-color: #FFF;
}}

/* ---------- 汇总 ---------- */
QLabel#sumOk   {{ color: {OK};   font-weight: 700; font-size: 14px; background: transparent; }}
QLabel#sumSkip {{ color: {WARN}; font-weight: 700; font-size: 14px; background: transparent; }}
QLabel#sumFail {{ color: {ERR};  font-weight: 700; font-size: 14px; background: transparent; }}
QLabel#brand   {{ color: {INK};  font-size: 17px; font-weight: 700; background: transparent; }}
QLabel#ver     {{ color: {INK3}; font-size: 11px; background: transparent; }}
"""


# ---------------------------------------------------------------------------
# 黑胶 Logo（QPainter 纯色绘制，无渐变）
# ---------------------------------------------------------------------------
def vinyl_pixmap(size=40, color=INK):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    try:
        d = size
        # 唱片外沿
        p.setPen(QPen(QColor(color), max(1, d // 20)))
        p.setBrush(QBrush(QColor(color)))
        p.drawEllipse(2, 2, d - 4, d - 4)
        # 纹路（浅色圈）
        p.setBrush(Qt.NoBrush)
        pen = QPen(QColor("#F5F5F5"))
        pen.setWidthF(max(1.0, d / 26))
        p.setPen(pen)
        for r in (0.72, 0.60, 0.48):
            rr = int(d * r)
            off = (d - rr) // 2
            p.drawEllipse(off, off, rr, rr)
        # 标签区
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#F5F5F5")))
        rr = int(d * 0.34)
        off = (d - rr) // 2
        p.drawEllipse(off, off, rr, rr)
        p.setBrush(QBrush(QColor(color)))
        rr = int(d * 0.06)
        off = (d - rr) // 2
        p.drawEllipse(off, off, rr, rr)
    finally:
        p.end()
    return pm


# ---------------------------------------------------------------------------
# 后台工作线程：跑核心引擎，信号回 UI
# ---------------------------------------------------------------------------
class Worker(QObject):
    sig_log = Signal(str)                 # 一条 HTML 日志
    sig_progress = Signal(int, int, str)  # done, total, src
    sig_done = Signal(dict)               # stats

    def __init__(self, items, args):
        super().__init__()
        self.items = items
        self.args = args
        self._cancel = threading.Event()

    def run(self):
        core.cache_load()
        total = len(self.items)
        stats = {"ok": 0, "skip": 0, "fail": 0}
        lock = threading.Lock()

        def task(idx, src, out):
            try:
                return idx, src, core.enrich_one(src, out, self.args)
            except Exception as e:            # noqa: BLE001
                return idx, src, f"✗ 处理出错: {type(e).__name__}: {e}"

        jobs = max(1, int(self.args.jobs))
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(task, i, s, o): s for i, (s, o)
                    in enumerate(self.items, 1)}
            done = 0
            for fut in as_completed(futs):
                idx, src, res = fut.result()
                with lock:
                    done += 1
                    if "✗" in res or "失败" in res or "处理出错" in res:
                        stats["fail"] += 1
                    elif res.startswith("跳过"):
                        stats["skip"] += 1
                    else:
                        stats["ok"] += 1
                self.sig_progress.emit(done, total, src)
                self._emit_result(src, res)
                if self._cancel.is_set():
                    try:                    # cancel_futures 需要 Python 3.9+
                        ex.shutdown(wait=False, cancel_futures=True)
                    except TypeError:       # Python 3.8 回退
                        ex.shutdown(wait=False)
                    self.sig_log.emit(
                        f'<span style="color:{ERR}">■ 已由用户取消，'
                        f'未处理项已放弃（缓存已保存）</span>')
                    break
        core.cache_save(self.args.cache)
        self.sig_done.emit(stats)

    def _emit_result(self, src, res):
        base = os.path.basename(src)
        color = INK2
        mark = "·"
        if "✗" in res or "失败" in res or "处理出错" in res:
            color, mark = ERR, "✗"
        elif res.startswith("跳过"):
            color, mark = WARN, "·"
        else:
            color, mark = OK, "✓"
        body = res.replace("&", "&amp;").replace("<", "&lt;") \
                  .replace("\n", "<br>")
        self.sig_log.emit(
            f'<div style="margin:2px 0"><span style="color:{color};'
            f'font-weight:700">{mark} {base}</span><br>'
            f'<span style="color:{INK3}">{body}</span></div>')


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.paths = []            # 用户选中的文件/文件夹
        self.items = []            # collect_files 之后 (src, out)
        self.worker = None
        self.thread = None
        self._blink = 0
        self.settings = QSettings("SleeveLiner", "GUI")
        self.setWindowTitle("SleeveLiner — 封面与歌词自动补齐")
        self.setMinimumSize(760, 660)
        self.resize(760, 700)
        self.setAcceptDrops(True)
        self._build_ui()
        self._load_settings()
        self._bind_shortcuts()

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        col = QVBoxLayout(root)
        col.setContentsMargins(24, 20, 24, 18)
        col.setSpacing(14)

        # 顶栏：logo + 名称 + 版本（同行，底对齐）
        top = QHBoxLayout()
        top.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(vinyl_pixmap(40))
        top.addWidget(logo)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        brand_row.setAlignment(Qt.AlignVCenter)
        brand = QLabel("SleeveLiner", objectName="brand")
        ver = QLabel(f"v{core.VERSION}", objectName="ver")
        brand_row.addWidget(brand, 0, Qt.AlignVCenter)
        brand_row.addWidget(ver, 0, Qt.AlignVCenter)
        tcol = QVBoxLayout()
        tcol.setSpacing(1)
        tcol.addLayout(brand_row)
        tsub = QLabel("封面与歌词自动补齐 · 原文件永不改动", objectName="ver")
        tcol.addWidget(tsub)
        top.addLayout(tcol)
        top.addStretch(1)
        col.addLayout(top)

        # 拖放区
        self.drop = QFrame(objectName="drop")
        self.drop.setAcceptDrops(True)
        self.setAcceptDrops(True)
        dcol = QVBoxLayout(self.drop)
        dcol.setContentsMargins(18, 16, 18, 14)
        dcol.setSpacing(4)
        dtitle = QLabel("拖入音乐文件或文件夹", objectName="dropTitle")
        dtitle.setAlignment(Qt.AlignCenter)
        dhint = QLabel("支持 MP3 / FLAC / M4A / OPUS / OGG — 结果输出到 output/ 文件夹",
                       objectName="dropHint")
        dhint.setAlignment(Qt.AlignCenter)
        self.dcount = QLabel("尚未选择任何内容", objectName="dropCount")
        self.dcount.setAlignment(Qt.AlignCenter)
        dcol.addWidget(dtitle)
        dcol.addWidget(dhint)
        dcol.addSpacing(6)
        dcol.addWidget(self.dcount)
        self.drop.dragEnterEvent = self._drag_enter
        self.drop.dragLeaveEvent = self._drag_leave
        self.drop.dropEvent = self._drop
        col.addWidget(self.drop, 1)

        # 选择按钮行（一组靠左，清空收尾）
        brow = QHBoxLayout()
        brow.setSpacing(8)
        b_file = QPushButton("选择文件…")
        b_dir = QPushButton("选择文件夹…")
        b_clear = QPushButton("清空")
        b_file.clicked.connect(lambda: self._browse(True))
        b_dir.clicked.connect(lambda: self._browse(False))
        b_clear.clicked.connect(self._clear)
        brow.addWidget(b_file)
        brow.addWidget(b_dir)
        brow.addWidget(b_clear)
        brow.addStretch(1)
        col.addLayout(brow)

        # 选项区（白卡片，左右两组用细分隔线隔开）
        optcard = QFrame(objectName="optCard")
        orow = QHBoxLayout(optcard)
        orow.setContentsMargins(16, 10, 16, 10)
        orow.setSpacing(12)
        self.cb_recursive = QCheckBox("递归子目录")
        self.cb_recursive.setChecked(True)
        self.cb_rename = QCheckBox("规范文件名")
        self.cb_force = QCheckBox("覆盖已有")
        self.sp_jobs = QSpinBox()
        self.sp_jobs.setRange(1, 32)
        self.sp_jobs.setValue(4)
        self.sp_jobs.setFixedWidth(64)
        self.cb_encoding = QComboBox()
        self.cb_encoding.addItems(["UTF-8", "GBK"])
        self.cb_encoding.setFixedWidth(96)
        lab_jobs = QLabel("线程")
        lab_enc = QLabel("歌词编码")
        orow.addWidget(self.cb_recursive)
        orow.addWidget(self.cb_rename)
        orow.addWidget(self.cb_force)
        orow.addStretch(1)
        vline = QFrame(objectName="vline")
        vline.setFixedWidth(1)
        vline.setFixedHeight(20)
        orow.addWidget(vline)
        orow.addStretch(1)
        orow.addWidget(lab_jobs)
        orow.addWidget(self.sp_jobs)
        orow.addWidget(lab_enc)
        orow.addWidget(self.cb_encoding)
        col.addWidget(optcard)

        # 高级（默认折叠）：手动指定歌手/歌名、查看待处理列表
        advrow = QHBoxLayout()
        advrow.setSpacing(8)
        self.btn_adv = QPushButton("高级选项 ▾")
        self.btn_adv.setCheckable(True)
        self.btn_adv.clicked.connect(self._toggle_adv)
        self.btn_list = QPushButton("查看待处理文件")
        self.btn_list.clicked.connect(self._show_list)
        advrow.addWidget(self.btn_adv)
        advrow.addWidget(self.btn_list)
        advrow.addStretch(1)
        col.addLayout(advrow)

        self.adv = QFrame(objectName="optCard")
        arow = QHBoxLayout(self.adv)
        arow.setContentsMargins(16, 10, 16, 10)
        arow.setSpacing(10)
        arow.addWidget(QLabel("手动指定"))
        self.ed_artist = QLineEdit()
        self.ed_artist.setPlaceholderText("歌手（留空自动识别）")
        self.ed_title = QLineEdit()
        self.ed_title.setPlaceholderText("歌名（留空自动识别）")
        arow.addWidget(self.ed_artist, 1)
        arow.addWidget(self.ed_title, 1)
        self.adv.setVisible(False)
        col.addWidget(self.adv)

        # 开始 / 停止
        self.btn_go = QPushButton("开始处理", objectName="go")
        self.btn_go.clicked.connect(self._start)
        self.btn_go.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_stop = QPushButton("停止", objectName="stop")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_stop.setVisible(False)
        grow = QHBoxLayout()
        grow.addWidget(self.btn_go, 1)
        grow.addWidget(self.btn_stop)
        col.addLayout(grow)

        # 进度
        pgrid = QGridLayout()
        pgrid.setHorizontalSpacing(10)
        pgrid.setVerticalSpacing(2)
        self.lab_count = QLabel("就绪", objectName="statLabel")
        self.lab_count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lab_file = QLabel("", objectName="statFile")
        self.bar = _FlatBar()
        pgrid.addWidget(self.lab_file, 0, 0)
        pgrid.addWidget(self.lab_count, 0, 1)
        pgrid.addWidget(self.bar, 1, 0, 1, 2)
        col.addLayout(pgrid)
        # 处理中：文件名呼吸动画
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._tick_blink)

        # 日志
        self.log = QTextEdit(objectName="log")
        self.log.setReadOnly(True)
        pal = self.log.palette()
        pal.setColor(QPalette.PlaceholderText, QColor("#8A8A8A"))
        self.log.setPalette(pal)
        self.log.setPlaceholderText("处理日志会显示在这里…")
        col.addWidget(self.log, 2)

        # 汇总行（与按钮垂直居中对齐）
        srow = QHBoxLayout()
        self.sum_ok = QLabel("成功 0", objectName="sumOk")
        self.sum_skip = QLabel("跳过 0", objectName="sumSkip")
        self.sum_fail = QLabel("失败 0", objectName="sumFail")
        for w in (self.sum_ok, self.sum_skip, self.sum_fail):
            w.setMinimumHeight(34)
            w.setAlignment(Qt.AlignVCenter)
        self.btn_open = QPushButton("打开 output 文件夹")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_output)
        srow.addWidget(self.sum_ok)
        srow.addSpacing(18)
        srow.addWidget(self.sum_skip)
        srow.addSpacing(18)
        srow.addWidget(self.sum_fail)
        srow.addStretch(1)
        srow.addWidget(self.btn_open)
        col.addLayout(srow)

    # ---------------- 扁平进度条 ----------------
    class _Bar(QFrame):
        pass

    # ---------------- 拖放 ----------------
    def dragEnterEvent(self, e):            # 窗口级兜底
        self._drag_enter(e)

    def _drag_enter(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.drop.setProperty("hover", True)
            self._repolish(self.drop)

    def _drag_leave(self, e):
        self.drop.setProperty("hover", False)
        self._repolish(self.drop)

    def dropEvent(self, e):
        self._drop(e)

    def _drop(self, e):
        self.drop.setProperty("hover", False)
        self._repolish(self.drop)
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self._add_paths(files)

    # ---------------- 选择 ----------------
    def _browse(self, is_file):
        if is_file:
            fl, _ = QFileDialog.getOpenFileNames(
                self, "选择音频文件", "", "音频 (*.mp3 *.flac *.m4a *.opus *.ogg *.oga *.aac)")
        else:
            fl = QFileDialog.getExistingDirectory(self, "选择文件夹")
            fl = [fl] if fl else []
        self._add_paths(fl)

    def _add_paths(self, paths):
        for p in paths:
            p = os.path.abspath(p)
            if p not in self.paths:
                self.paths.append(p)
        self._refresh()

    def _clear(self):
        self.paths.clear()
        self._refresh()

    def _refresh(self):
        self.items = core.collect_files(self.paths, self.cb_recursive.isChecked(),
                                        "output")
        n_audio = len(self.items)
        n_dir = sum(1 for p in self.paths if os.path.isdir(p))
        bits = []
        if n_audio:
            bits.append(f"待处理 {n_audio} 个音频")
        if n_dir:
            bits.append(f"{n_dir} 个文件夹")
        if self.paths and not n_audio:
            bits.append("（其中没有可处理的音频文件）")
        self.dcount.setText(" · ".join(bits) if bits else "尚未选择任何内容")
        self.btn_go.setEnabled(bool(self.items) and not self._running())
        self.btn_list.setEnabled(bool(self.items))
        self.btn_list.setToolTip("" if self.items else "暂无待处理文件")

    # ---------------- 高级 / 设置 ----------------
    def _toggle_adv(self, checked):
        self.adv.setVisible(bool(checked))
        self.btn_adv.setText("高级选项 ▴" if checked else "高级选项 ▾")

    def _show_list(self):
        if not self.items:
            self._log("还没有选择任何音频文件", WARN)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"待处理文件（{len(self.items)} 个）")
        dlg.resize(640, 440)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        lst = QListWidget()
        for src, _out in self.items[:2000]:
            item = QListWidgetItem(os.path.basename(src))
            item.setToolTip(src)
            lst.addItem(item)
        lay.addWidget(lst)
        if len(self.items) > 2000:
            lay.addWidget(QLabel(f"（仅显示前 2000 项，共 {len(self.items)} 项）"))
        btn = QPushButton("关闭")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn, 0, Qt.AlignRight)
        dlg.exec()

    def _load_settings(self):
        s = self.settings
        try:
            self.sp_jobs.setValue(int(s.value("jobs", 4)))
            idx = self.cb_encoding.findText(str(s.value("encoding", "UTF-8")))
            if idx >= 0:
                self.cb_encoding.setCurrentIndex(idx)
            self.cb_recursive.setChecked(str(s.value("recursive", "true")) == "true")
            self.cb_rename.setChecked(str(s.value("rename", "false")) == "true")
            self.cb_force.setChecked(str(s.value("force", "false")) == "true")
            geo = s.value("geometry")
            if geo:
                self.restoreGeometry(geo)
        except Exception:      # noqa: BLE001
            pass

    def _save_settings(self):
        s = self.settings
        s.setValue("jobs", self.sp_jobs.value())
        s.setValue("encoding", self.cb_encoding.currentText())
        s.setValue("recursive", self.cb_recursive.isChecked())
        s.setValue("rename", self.cb_rename.isChecked())
        s.setValue("force", self.cb_force.isChecked())
        s.setValue("geometry", self.saveGeometry())

    def closeEvent(self, e):
        self._save_settings()
        super().closeEvent(e)

    def _bind_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+O"), self,
                  activated=lambda: self._browse(True))
        QShortcut(QKeySequence("Ctrl+Shift+O"), self,
                  activated=lambda: self._browse(False))
        QShortcut(QKeySequence("F5"), self, activated=self._start)
        QShortcut(QKeySequence("Esc"), self, activated=self._stop)

    # ---------------- 开始 / 停止 ----------------
    def _running(self):
        return self.thread is not None and self.thread.is_alive()

    def _make_args(self):
        return argparse.Namespace(
            paths=self.paths, recursive=self.cb_recursive.isChecked(),
            artist=self.ed_artist.text().strip(),
            title=self.ed_title.text().strip(),
            tol=5.0, jobs=self.sp_jobs.value(),
            rename=self.cb_rename.isChecked(), outdir="output",
            lrc_encoding=self.cb_encoding.currentText().lower(),
            no_cache=False, no_cover=False, no_lyric=False, no_meta=False,
            no_lrc_file=False, force=self.cb_force.isChecked(), dry_run=False,
            cache=True)

    def _start(self):
        if not self.items:
            return
        self.log.clear()
        self.sum_ok.setText("成功 0")
        self.sum_skip.setText("跳过 0")
        self.sum_fail.setText("失败 0")
        self.btn_open.setEnabled(False)
        self.bar.set_value(0)
        self._set_running(True)
        self.lab_file.setText("正在启动…")
        self._blink_timer.start(600)
        args = self._make_args()
        self.items = core.collect_files(self.paths, args.recursive, "output")
        self._log(f'开始处理 {len(self.items)} 个文件 · '
                  f'{args.jobs} 线程 · 输出到 output/', INK2)

        self.worker = Worker(self.items, args)
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker.sig_log.connect(self._log)
        self.worker.sig_progress.connect(self._on_progress)
        self.worker.sig_done.connect(self._on_done)
        self.thread.start()

    def _stop(self):
        if self.worker:
            self.worker._cancel.set()
        self.btn_stop.setEnabled(False)
        self._log("正在停止…（等待进行中的文件完成）", WARN)

    def _set_running(self, on):
        self.btn_go.setVisible(not on)
        self.btn_stop.setVisible(on)
        self.btn_stop.setEnabled(True)
        self.drop.setEnabled(not on)

    # ---------------- 回调 ----------------
    def _on_progress(self, done, total, src):
        pct = int(done * 100 / max(total, 1))
        self.bar.set_value(pct, animated=True)
        self.lab_count.setText(f"{done} / {total} · {pct}%")
        name = os.path.basename(src)
        self.lab_file.setText(name if len(name) <= 46 else name[:44] + "…")

    def _on_done(self, stats):
        self._blink_timer.stop()
        self.lab_file.setText("")
        self.lab_file.setStyleSheet("")
        self.lab_count.setText("完成")
        self._set_running(False)
        self.btn_go.setEnabled(bool(self.items))
        self.btn_open.setEnabled(True)
        self.sum_ok.setText(f"成功 {stats['ok']}")
        self.sum_skip.setText(f"跳过 {stats['skip']}")
        self.sum_fail.setText(f"失败 {stats['fail']}")
        color = OK if stats["fail"] == 0 else (ERR if stats["ok"] == 0 else WARN)
        self._log(f"完成：成功 {stats['ok']} / 跳过 {stats['skip']} "
                  f"/ 失败 {stats['fail']}", color, big=True)
        for note in core.consume_notices():
            self._log(note, WARN)

    def _tick_blink(self):
        self._blink = (self._blink + 1) % 2
        self.lab_file.setStyleSheet(
            f"color: {INK2 if self._blink else INK3};")

    def _log(self, text, color=INK2, big=False):
        size = "15px" if big else "12px"
        weight = "700" if big else "400"
        self.log.append(f'<div style="color:{color};font-size:{size};'
                        f'font-weight:{weight};margin:4px 0">{text}</div>')
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _open_output(self):
        if not self.paths:
            return
        p = self.paths[0]
        out = os.path.join(p, "output") if os.path.isdir(p) \
            else os.path.join(os.path.dirname(p), "output")
        if not os.path.isdir(out):
            os.makedirs(out, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    @staticmethod
    def _repolish(w):
        w.style().unpolish(w)
        w.style().polish(w)


# ---------------------------------------------------------------------------
# 扁平进度条（细横条，纯色，无渐变无阴影；数值变化带平滑动画）
# ---------------------------------------------------------------------------
class _FlatBar(QFrame):
    STEP = 2

    def __init__(self):
        super().__init__()
        self.setFixedHeight(6)
        self._target = 0
        self._cur = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_value(self, pct, animated=False):
        self._target = max(0, min(100, pct))
        if animated:
            if not self._timer.isActive():
                self._timer.start(16)
        else:
            self._cur = self._target
            self._timer.stop()
            self.update()

    def _tick(self):
        if self._cur < self._target:
            self._cur = min(self._target, self._cur + self.STEP)
            self.update()
        else:
            self._timer.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        try:
            w, h = self.width(), self.height()
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#D9D9D9")))
            p.drawRoundedRect(0, 0, w, h, 3, 3)
            if self._cur > 0:
                p.setBrush(QBrush(QColor(INK)))
                p.drawRoundedRect(0, 0, int(w * self._cur / 100), h, 3, 3)
        finally:
            p.end()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def run_app(argv):
    app = QApplication(argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    QGuiApplication.setFont(QFont("Noto Sans SC", 10))
    win = MainWindow()
    win.show()
    return app.exec()


def _selftest():
    """无显示器环境自测：构建 UI → 加入合成音频 → 真实跑完 → 截图退出。"""
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="sl_gui_")
    src_dir = os.path.join(tmp, "input")
    os.makedirs(src_dir, exist_ok=True)
    fake = os.path.join(src_dir, "周杰伦-晴天.mp3")
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=269",
                    "-b:a", "128k", fake], check=True)

    app = QApplication(["sleeveliner-gui"])
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.resize(760, 680)
    win.show()
    win._add_paths([src_dir])
    win.grab().save("/tmp/gui_shot_init.png")

    win._start()

    def check():
        if not win._running():
            win.grab().save("/tmp/gui_shot_done.png")
            ok = (win.sum_ok.text().split()[-1] != "0"
                  and os.path.exists(os.path.join(src_dir, "output",
                                                  "周杰伦-晴天.mp3")))
            print("SELFTEST", "OK" if ok else "FAIL",
                  win.sum_ok.text(), win.sum_skip.text(), win.sum_fail.text())
            app.exit(0 if ok else 1)
            return
        QTimer.singleShot(300, check)

    QTimer.singleShot(500, check)
    app.exec()
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(0)


def main():
    if "--gui-selftest" in sys.argv:
        _selftest()
    sys.exit(run_app(sys.argv))


if __name__ == "__main__":
    main()
