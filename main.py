#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 极致压缩工具 - GUI 版
依赖: pip install pikepdf pillow
可选: pip install tkinterdnd2   (启用拖拽)
系统: Ghostscript
"""

import os
import re
import sys
import glob
import shutil
import subprocess
import threading
import queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception:
    HAS_DND = False


# ============================================================
#  Ghostscript 查找
# ============================================================

_GS_PATH = None


def _bundled_gs():
    if hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    elif getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent

    for name in ("gswin64c.exe", "gswin32c.exe", "gs.exe"):
        p = base / "gs" / "bin" / name
        if p.exists():
            return str(p)
    return None


def _candidate_names():
    if sys.platform.startswith("win"):
        return ["gswin64c.exe", "gswin64c", "gswin32c.exe", "gswin32c", "gs.exe", "gs"]
    return ["gs"]


def _scan_windows_install_dirs():
    patterns = [
        r"C:\Program Files\gs\*\bin\gswin64c.exe",
        r"C:\Program Files\gs\*\bin\gswin32c.exe",
        r"C:\Program Files (x86)\gs\*\bin\gswin64c.exe",
        r"C:\Program Files (x86)\gs\*\bin\gswin32c.exe",
        r"C:\Program Files\gs\*\bin\gs.exe",
    ]
    found = []
    for pat in patterns:
        found.extend(glob.glob(pat))

    def ver_key(p):
        m = re.search(r"gs[\\/]([0-9.]+)[\\/]", p)
        return [int(x) for x in m.group(1).split(".")] if m else [0]

    found.sort(key=ver_key, reverse=True)
    return found


def find_ghostscript(manual_path=None, verbose=False):
    global _GS_PATH
    logs = []

    b = _bundled_gs()
    if b:
        _GS_PATH = b
        logs.append(f"[OK] 内置: {b}")
        if verbose: print("\n".join(logs))
        return _GS_PATH

    if manual_path:
        p = Path(manual_path)
        if p.is_file():
            _GS_PATH = str(p)
            logs.append(f"[OK] 手动指定: {_GS_PATH}")
            if verbose: print("\n".join(logs))
            return _GS_PATH
        logs.append(f"[X] 手动路径不是文件: {manual_path}")

    for name in _candidate_names():
        w = shutil.which(name)
        if w:
            if w.lower().endswith((".cmd", ".bat")):
                logs.append(f"[!] {w} 是脚本，跳过")
                continue
            _GS_PATH = w
            logs.append(f"[OK] PATH: {w}")
            if verbose: print("\n".join(logs))
            return _GS_PATH

    if sys.platform.startswith("win"):
        for p in _scan_windows_install_dirs():
            _GS_PATH = p
            logs.append(f"[OK] 扫描: {p}")
            if verbose: print("\n".join(logs))
            return _GS_PATH

    logs.append("[X] 未找到 Ghostscript")
    if verbose: print("\n".join(logs))
    return None


def get_gs_path():
    return _GS_PATH or find_ghostscript()


# ============================================================
#  压缩核心
# ============================================================

QUALITY_SETTINGS = {
    "screen":  {"c": 72,  "g": 72,  "m": 200, "q": 30},
    "ebook":   {"c": 150, "g": 150, "m": 300, "q": 55},
    "printer": {"c": 300, "g": 300, "m": 600, "q": 75},
}

# 栅格化模式的推荐 DPI（小于这个值文字会明显糊）
RASTER_PRESETS = {
    "screen":  100,
    "ebook":   150,
    "printer": 200,
}


def _run_gs(cmd):
    _creation_flags = 0
    if sys.platform.startswith("win"):
        _creation_flags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, creationflags=_creation_flags)
    except FileNotFoundError as e:
        raise RuntimeError(f"无法执行 Ghostscript: {cmd[0]}\n{e}")
    except OSError as e:
        raise RuntimeError(f"调用 Ghostscript 失败: {e}")

    if result.returncode != 0:
        err = (result.stderr or "").strip() or (result.stdout or "").strip()
        raise RuntimeError(
            f"Ghostscript 返回码 {result.returncode}\n错误: {err[:800]}")


def compress_with_ghostscript(input_path, output_path, params):
    """
    标准压缩：保留文字矢量，只对图片降采样/重编码。
    """
    gs = get_gs_path()
    if not gs:
        raise RuntimeError("未找到 Ghostscript，请在设置里手动指定 gswin64c.exe")

    quality = params.get("quality", "screen")
    preset = QUALITY_SETTINGS.get(quality, QUALITY_SETTINGS["screen"])

    c = int(params.get("color_dpi", preset["c"]))
    g = int(params.get("gray_dpi",  preset["g"]))
    m = int(params.get("mono_dpi",  preset["m"]))
    q = int(params.get("jpeg_q",    preset["q"]))
    grayscale = bool(params.get("grayscale", False))

    cmd = [
        gs,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dPDFSETTINGS=/" + quality,
        f"-dColorImageResolution={c}",
        f"-dGrayImageResolution={g}",
        f"-dMonoImageResolution={m}",
        "-dColorImageDownsampleType=/Bicubic",
        "-dGrayImageDownsampleType=/Bicubic",
        "-dMonoImageDownsampleType=/Subsample",
        "-dDownsampleColorImages=true",
        "-dDownsampleGrayImages=true",
        "-dDownsampleMonoImages=true",
        "-dAutoFilterColorImages=false",
        "-dAutoFilterGrayImages=false",
        "-dColorImageFilter=/DCTEncode",
        "-dGrayImageFilter=/DCTEncode",
        f"-dJPEGQ={q}",
        "-dEmbedAllFonts=true",
        "-dSubsetFonts=true",
        "-dCompressFonts=true",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={output_path}",
    ]

    if grayscale:
        cmd += [
            "-sColorConversionStrategy=Gray",
            "-dProcessColorModel=/DeviceGray",
        ]

    cmd.append(str(input_path))
    _run_gs(cmd)

    if not Path(output_path).exists():
        raise RuntimeError("Ghostscript 未生成输出文件")


def compress_with_rasterize(input_path, output_path, params):
    """
    整页栅格化：把每页渲染成图片再打包，能显著缩小文字型 PDF。
    代价：不可搜索、不可选中、放大模糊。
    """
    gs = get_gs_path()
    if not gs:
        raise RuntimeError("未找到 Ghostscript，请在设置里手动指定 gswin64c.exe")

    quality = params.get("quality", "screen")
    dpi = int(params.get("raster_dpi", RASTER_PRESETS.get(quality, 120)))
    jpeg_q = int(params.get("jpeg_q", 40))
    grayscale = bool(params.get("grayscale", False))

    # pdfimage8 = 8bit 灰度；pdfimage24 = 24bit 彩色
    device = "pdfimage8" if grayscale else "pdfimage24"

    cmd = [
        gs,
        f"-sDEVICE={device}",
        f"-r{dpi}",
        "-dDownsampleColorImages=true",
        "-dDownsampleGrayImages=true",
        "-dDownsampleMonoImages=true",
        f"-dColorImageResolution={dpi}",
        f"-dGrayImageResolution={dpi}",
        "-dAutoFilterColorImages=false",
        "-dAutoFilterGrayImages=false",
        "-dColorImageFilter=/DCTEncode",
        "-dGrayImageFilter=/DCTEncode",
        f"-dJPEGQ={jpeg_q}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={output_path}",
        str(input_path),
    ]

    _run_gs(cmd)

    if not Path(output_path).exists():
        raise RuntimeError("Ghostscript 未生成输出文件")


def compress_with_pikepdf(input_path, output_path, params):
    """
    pikepdf 二次优化：重编码内嵌图片 + 重压缩流。
    """
    import pikepdf
    from PIL import Image
    import io

    max_dim = int(params.get("max_dim", 1200))
    jpeg_q = int(params.get("pikepdf_q", 40))
    grayscale = bool(params.get("grayscale", False))

    with pikepdf.open(input_path) as pdf:
        pdf.remove_unreferenced_resources()

        for page in pdf.pages:
            try:
                resources = page.get("/Resources", {})
                xobjects = resources.get("/XObject", {})
                for name, obj in list(xobjects.items()):
                    try:
                        if obj.get("/Subtype") != "/Image":
                            continue
                        img_data = obj.read_raw_bytes()
                        try:
                            img = Image.open(io.BytesIO(img_data))
                        except Exception:
                            continue

                        if grayscale:
                            img = img.convert("L")
                        elif img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")

                        if max_dim > 0 and max(img.size) > max_dim:
                            ratio = max_dim / max(img.size)
                            img = img.resize(
                                (int(img.width * ratio), int(img.height * ratio)),
                                Image.LANCZOS,
                            )

                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=jpeg_q, optimize=True)
                        new_data = buf.getvalue()
                        if len(new_data) < len(img_data):
                            obj.write(new_data, filter=pikepdf.Name("/DCTDecode"))
                            obj["/Width"] = img.width
                            obj["/Height"] = img.height
                    except Exception:
                        continue
            except Exception:
                continue

        pdf.save(output_path, compress_streams=True,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate,
                 linearize=True)


# ---------- PDF 图片统计 ----------

def pdf_image_stats(path):
    """
    返回 (图片数量, 最大边长 px)。失败时返回 (0, 0)。
    用于判断"文字型 PDF 压不动"。
    """
    try:
        import pikepdf
        n, max_side = 0, 0
        with pikepdf.open(path) as pdf:
            for page in pdf.pages:
                try:
                    xo = page.get("/Resources", {}).get("/XObject", {})
                    for name, obj in xo.items():
                        try:
                            if obj.get("/Subtype") != "/Image":
                                continue
                            n += 1
                            w = int(obj.get("/Width", 0))
                            h = int(obj.get("/Height", 0))
                            max_side = max(max_side, w, h)
                        except Exception:
                            continue
                except Exception:
                    continue
        return n, max_side
    except Exception:
        return 0, 0


# ---------- 单文件压缩 ----------

def compress_one(input_path, output_path, params):
    """
    返回 (orig_kb, new_kb, kept_original, mode_note)
      kept_original - True 表示压缩后反而变大，保留了原文件
      mode_note     - "raster" / "" （供 UI 显示）
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tmp1 = output_path.with_suffix(".t1.pdf")
    tmp2 = output_path.with_suffix(".t2.pdf")
    for t in (tmp1, tmp2):
        if t.exists():
            t.unlink()

    orig_kb = os.path.getsize(input_path) / 1024
    mode = params.get("mode", "standard")   # standard | raster

    # ---- 第一步：Ghostscript ----
    if mode == "raster":
        compress_with_rasterize(input_path, tmp1, params)
    else:
        compress_with_ghostscript(input_path, tmp1, params)
    current = tmp1

    # ---- 第二步：pikepdf（栅格化模式下没必要） ----
    if mode != "raster" and params.get("use_pikepdf", True):
        try:
            compress_with_pikepdf(current, tmp2, params)
            if os.path.getsize(tmp2) < os.path.getsize(current):
                os.remove(current)
                current = tmp2
            else:
                os.remove(tmp2)
        except ImportError:
            pass
        except Exception:
            # 二次优化失败不影响主结果
            if tmp2.exists():
                tmp2.unlink()

    # ---- 第三步：变大则保留原文件 ----
    if os.path.getsize(current) >= os.path.getsize(input_path):
        for t in (tmp1, tmp2):
            if t.exists():
                t.unlink()
        if output_path.exists():
            output_path.unlink()
        shutil.copy2(input_path, output_path)
        new_kb = os.path.getsize(output_path) / 1024
        return orig_kb, new_kb, True, mode

    if output_path.exists():
        output_path.unlink()
    shutil.move(str(current), str(output_path))
    new_kb = os.path.getsize(output_path) / 1024
    return orig_kb, new_kb, False, mode


# ============================================================
#  GUI
# ============================================================

class PDFCompressorGUI:
    def __init__(self, root):
        self.root = root
        root.title("PDF 极致压缩工具")
        root.geometry("880x800")
        root.minsize(780, 660)

        self.files = []
        self.msg_queue = queue.Queue()
        self.worker = None
        self.cancel_flag = False
        self.manual_gs = ""
        self.advanced_open = False

        self._build_ui()
        self._detect_gs_async()
        self._poll_queue()

    # ---------- UI ----------
    def _build_ui(self):
        try:
            ttk.Style().theme_use("clam")
        except Exception:
            pass

        # ===== 基本设置区 =====
        top = ttk.LabelFrame(self.root, text="压缩设置", padding=10)
        top.pack(fill="x", padx=10, pady=(10, 5))

        # --- 第一行：质量预设 / 压缩模式 ---
        ttk.Label(top, text="质量预设:").grid(row=0, column=0, sticky="w")
        self.quality_var = tk.StringVar(value="screen")
        qbox = ttk.Combobox(
            top, textvariable=self.quality_var, state="readonly", width=18,
            values=["screen (极致)", "ebook (平衡)", "printer (高质量)"],
        )
        qbox.current(0)
        qbox.grid(row=0, column=1, sticky="w", padx=(5, 15))
        qbox.bind("<<ComboboxSelected>>",
                  lambda e: self.quality_var.set(self.quality_var.get().split()[0]))

        ttk.Label(top, text="压缩模式:").grid(row=0, column=2, sticky="w")
        self.mode_var = tk.StringVar(value="standard")
        self.mode_box = ttk.Combobox(
            top, textvariable=self.mode_var, state="readonly", width=20,
            values=["标准（保持可搜索）", "整页栅格化（缩得更多）"],
        )
        self.mode_box.current(0)
        self.mode_box.grid(row=0, column=3, sticky="w", padx=(5, 15))
        self.mode_box.bind("<<ComboboxSelected>>", self._on_mode_changed)

        # --- 第二行：pikepdf / 覆盖 ---
        self.pikepdf_var = tk.BooleanVar(value=True)
        self.pikepdf_cb = ttk.Checkbutton(top, text="pikepdf 二次优化",
                                          variable=self.pikepdf_var)
        self.pikepdf_cb.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="覆盖同名输出",
                        variable=self.overwrite_var).grid(
            row=1, column=2, sticky="w", padx=(15, 0), pady=(8, 0))

        # --- 第三行：输出目录 ---
        ttk.Label(top, text="输出目录:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.outdir_var = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.outdir_var).grid(
            row=2, column=1, columnspan=3, sticky="we", padx=(5, 5), pady=(8, 0))
        ttk.Button(top, text="选择…", command=self._choose_outdir).grid(
            row=2, column=4, sticky="w", pady=(8, 0))

        # --- 第四行：Ghostscript ---
        ttk.Label(top, text="Ghostscript:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.gs_var = tk.StringVar(value="检测中…")
        ttk.Label(top, textvariable=self.gs_var, foreground="#666",
                  anchor="w").grid(row=3, column=1, columnspan=3,
                                   sticky="we", padx=(5, 5), pady=(8, 0))
        ttk.Button(top, text="重新检测", command=self._detect_gs_async).grid(
            row=3, column=4, sticky="w", pady=(8, 0))
        ttk.Button(top, text="手动指定", command=self._pick_gs_manual).grid(
            row=4, column=4, sticky="w", pady=(4, 0))

        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        # 栅格化提示
        self.raster_hint = ttk.Label(
            top, text="⚠ 栅格化模式会把文字变成图片，PDF 将不可搜索、放大模糊，"
                      "但体积能显著缩小。",
            foreground="#b35a00", wraplength=780, justify="left")
        # 初始不 pack；切到栅格化时 pack

        # ===== 进阶参数（可折叠） =====
        self._build_advanced_panel()

        # ===== 文件列表 =====
        mid = ttk.LabelFrame(self.root, text="文件列表（可拖拽 PDF 到此处）", padding=5)
        mid.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("name", "size", "status", "result")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=10)
        self.tree.heading("name", text="文件名")
        self.tree.heading("size", text="原始大小")
        self.tree.heading("status", text="状态")
        self.tree.heading("result", text="压缩结果")
        self.tree.column("name", width=340, anchor="w")
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("status", width=110, anchor="center")
        self.tree.column("result", width=230, anchor="e")

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda e: self._open_selected())
        self._setup_dnd()

        # ===== 按钮 =====
        btns = ttk.Frame(self.root)
        btns.pack(fill="x", padx=10, pady=(0, 5))

        ttk.Button(btns, text="添加文件", command=self._add_files).pack(side="left", padx=2)
        ttk.Button(btns, text="添加文件夹", command=self._add_folder).pack(side="left", padx=2)
        ttk.Button(btns, text="移除选中", command=self._remove_selected).pack(side="left", padx=2)
        ttk.Button(btns, text="清空列表", command=self._clear_list).pack(side="left", padx=2)
        ttk.Button(btns, text="统计图片", command=self._show_image_stats).pack(side="left", padx=2)

        self.start_btn = ttk.Button(btns, text="开始压缩", command=self._start)
        self.start_btn.pack(side="right", padx=2)
        self.cancel_btn = ttk.Button(btns, text="取消", command=self._cancel,
                                     state="disabled")
        self.cancel_btn.pack(side="right", padx=2)

        # ===== 进度 =====
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill="x")

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bottom, textvariable=self.status_var,
                  anchor="w").pack(fill="x", pady=(4, 0))

    # ---------- 进阶面板 ----------
    def _build_advanced_panel(self):
        outer = ttk.Frame(self.root)
        outer.pack(fill="x", padx=10, pady=(0, 5))

        self.adv_toggle_btn = ttk.Button(
            outer, text="▶ 进阶参数（点击展开）",
            command=self._toggle_advanced)
        self.adv_toggle_btn.pack(fill="x")

        self.adv_frame = ttk.LabelFrame(outer, text="", padding=10)
        self.adv_inner = self.adv_frame

        # ---- 图片采样 ----
        row = 0
        ttk.Label(self.adv_inner, text="图片采样（标准模式）",
                  font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=6, sticky="w", pady=(0, 4))

        row += 1
        ttk.Label(self.adv_inner, text="彩色 DPI:").grid(row=row, column=0, sticky="w")
        self.color_dpi_var = tk.IntVar(value=72)
        ttk.Spinbox(self.adv_inner, from_=30, to=600, increment=10,
                    textvariable=self.color_dpi_var, width=6).grid(
            row=row, column=1, sticky="w", padx=(5, 15))
        self.color_dpi_scale = ttk.Scale(
            self.adv_inner, from_=30, to=600, orient="horizontal",
            command=lambda v: self.color_dpi_var.set(int(float(v))))
        self.color_dpi_scale.set(72)
        self.color_dpi_scale.grid(row=row, column=2, columnspan=4, sticky="we")

        row += 1
        ttk.Label(self.adv_inner, text="灰度 DPI:").grid(row=row, column=0, sticky="w")
        self.gray_dpi_var = tk.IntVar(value=72)
        ttk.Spinbox(self.adv_inner, from_=30, to=600, increment=10,
                    textvariable=self.gray_dpi_var, width=6).grid(
            row=row, column=1, sticky="w", padx=(5, 15))
        self.gray_dpi_scale = ttk.Scale(
            self.adv_inner, from_=30, to=600, orient="horizontal",
            command=lambda v: self.gray_dpi_var.set(int(float(v))))
        self.gray_dpi_scale.set(72)
        self.gray_dpi_scale.grid(row=row, column=2, columnspan=4, sticky="we")

        row += 1
        ttk.Label(self.adv_inner, text="单色 DPI:").grid(row=row, column=0, sticky="w")
        self.mono_dpi_var = tk.IntVar(value=200)
        ttk.Spinbox(self.adv_inner, from_=100, to=1200, increment=50,
                    textvariable=self.mono_dpi_var, width=6).grid(
            row=row, column=1, sticky="w", padx=(5, 15))
        self.mono_dpi_scale = ttk.Scale(
            self.adv_inner, from_=100, to=1200, orient="horizontal",
            command=lambda v: self.mono_dpi_var.set(int(float(v))))
        self.mono_dpi_scale.set(200)
        self.mono_dpi_scale.grid(row=row, column=2, columnspan=4, sticky="we")

        # ---- 栅格化 DPI ----
        row += 1
        ttk.Separator(self.adv_inner, orient="horizontal").grid(
            row=row, column=0, columnspan=6, sticky="we", pady=8)

        row += 1
        ttk.Label(self.adv_inner, text="栅格化模式",
                  font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=6, sticky="w", pady=(0, 4))

        row += 1
        ttk.Label(self.adv_inner, text="栅格化 DPI:").grid(row=row, column=0, sticky="w")
        self.raster_dpi_var = tk.IntVar(value=120)
        ttk.Spinbox(self.adv_inner, from_=50, to=600, increment=10,
                    textvariable=self.raster_dpi_var, width=6).grid(
            row=row, column=1, sticky="w", padx=(5, 15))
        self.raster_dpi_scale = ttk.Scale(
            self.adv_inner, from_=50, to=600, orient="horizontal",
            command=lambda v: self.raster_dpi_var.set(int(float(v))))
        self.raster_dpi_scale.set(120)
        self.raster_dpi_scale.grid(row=row, column=2, columnspan=4, sticky="we")
        row += 1
        ttk.Label(self.adv_inner,
                  text="建议 100~150（越小越糊）；仅'整页栅格化'模式生效",
                  foreground="#888").grid(
            row=row, column=0, columnspan=6, sticky="w", pady=(2, 0))

        # ---- 画质与尺寸 ----
        row += 1
        ttk.Separator(self.adv_inner, orient="horizontal").grid(
            row=row, column=0, columnspan=6, sticky="we", pady=8)

        row += 1
        ttk.Label(self.adv_inner, text="画质与尺寸", font=("", 9, "bold")).grid(
            row=row, column=0, columnspan=6, sticky="w", pady=(0, 4))

        row += 1
        ttk.Label(self.adv_inner, text="JPEG 质量:").grid(row=row, column=0, sticky="w")
        self.jpeg_q_var = tk.IntVar(value=30)
        ttk.Spinbox(self.adv_inner, from_=5, to=95, increment=5,
                    textvariable=self.jpeg_q_var, width=6).grid(
            row=row, column=1, sticky="w", padx=(5, 15))
        self.jpeg_q_scale = ttk.Scale(
            self.adv_inner, from_=5, to=95, orient="horizontal",
            command=lambda v: self.jpeg_q_var.set(int(float(v))))
        self.jpeg_q_scale.set(30)
        self.jpeg_q_scale.grid(row=row, column=2, columnspan=4, sticky="we")

        row += 1
        ttk.Label(self.adv_inner, text="pikepdf 最大边:").grid(
            row=row, column=0, sticky="w")
        self.max_dim_var = tk.IntVar(value=1200)
        ttk.Spinbox(self.adv_inner, from_=0, to=5000, increment=100,
                    textvariable=self.max_dim_var, width=6).grid(
            row=row, column=1, sticky="w", padx=(5, 15))
        ttk.Label(self.adv_inner, text="px（0 = 不限制）",
                  foreground="#888").grid(row=row, column=2, columnspan=4, sticky="w")

        row += 1
        ttk.Label(self.adv_inner, text="pikepdf 质量:").grid(
            row=row, column=0, sticky="w")
        self.pikepdf_q_var = tk.IntVar(value=40)
        ttk.Spinbox(self.adv_inner, from_=5, to=95, increment=5,
                    textvariable=self.pikepdf_q_var, width=6).grid(
            row=row, column=1, sticky="w", padx=(5, 15))
        self.pikepdf_q_scale = ttk.Scale(
            self.adv_inner, from_=5, to=95, orient="horizontal",
            command=lambda v: self.pikepdf_q_var.set(int(float(v))))
        self.pikepdf_q_scale.set(40)
        self.pikepdf_q_scale.grid(row=row, column=2, columnspan=4, sticky="we")

        # ---- 颜色 ----
        row += 1
        ttk.Separator(self.adv_inner, orient="horizontal").grid(
            row=row, column=0, columnspan=6, sticky="we", pady=8)

        row += 1
        self.grayscale_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.adv_inner, text="强制转为灰度（扫描件省 30%~60%）",
                        variable=self.grayscale_var).grid(
            row=row, column=0, columnspan=6, sticky="w")

        # ---- 底部按钮 ----
        row += 1
        btn_row = ttk.Frame(self.adv_inner)
        btn_row.grid(row=row, column=0, columnspan=6, sticky="we", pady=(10, 0))
        ttk.Button(btn_row, text="跟随预设",
                   command=self._sync_advanced_to_preset).pack(side="left", padx=2)
        ttk.Button(btn_row, text="重置默认",
                   command=self._reset_advanced).pack(side="left", padx=2)
        ttk.Label(btn_row, text="修改预设或点“跟随预设”会覆盖以上数值",
                  foreground="#888").pack(side="left", padx=10)

        for c in range(2, 6):
            self.adv_inner.columnconfigure(c, weight=1)

        try:
            self.quality_var.trace_add("write", self._on_quality_var_changed)
        except Exception:
            pass

    def _toggle_advanced(self):
        if self.advanced_open:
            self.adv_frame.pack_forget()
            self.adv_toggle_btn.config(text="▶ 进阶参数（点击展开）")
            self.advanced_open = False
        else:
            self.adv_frame.pack(fill="x", pady=(5, 0))
            self.adv_toggle_btn.config(text="▼ 进阶参数（点击收起）")
            self.advanced_open = True

    def _on_quality_var_changed(self, *args):
        self._sync_advanced_to_preset()

    def _sync_advanced_to_preset(self):
        q = self.quality_var.get().split()[0] if self.quality_var.get() else "screen"
        preset = QUALITY_SETTINGS.get(q, QUALITY_SETTINGS["screen"])
        self.color_dpi_var.set(preset["c"])
        self.color_dpi_scale.set(preset["c"])
        self.gray_dpi_var.set(preset["g"])
        self.gray_dpi_scale.set(preset["g"])
        self.mono_dpi_var.set(preset["m"])
        self.mono_dpi_scale.set(preset["m"])
        self.jpeg_q_var.set(preset["q"])
        self.jpeg_q_scale.set(preset["q"])
        # 栅格化 DPI 也跟着预设走
        self.raster_dpi_var.set(RASTER_PRESETS.get(q, 120))
        self.raster_dpi_scale.set(RASTER_PRESETS.get(q, 120))

    def _reset_advanced(self):
        self.max_dim_var.set(1200)
        self.pikepdf_q_var.set(40)
        self.pikepdf_q_scale.set(40)
        self.grayscale_var.set(False)

    # ---------- 模式切换 ----------
    def _on_mode_changed(self, event=None):
        mode = self._current_mode()
        if mode == "raster":
            # 显示提示
            self.raster_hint.pack(fill="x", padx=10, pady=(0, 4), before=self.adv_toggle_btn.master)
            # 栅格化时禁用 pikepdf（无意义）
            self.pikepdf_var.set(False)
            self.pikepdf_cb.config(state="disabled")
        else:
            self.raster_hint.pack_forget()
            self.pikepdf_cb.config(state="normal")

    def _current_mode(self):
        return "raster" if "栅格" in self.mode_var.get() else "standard"

    # ---------- GS 检测 ----------
    def _detect_gs_async(self):
        self.gs_var.set("检测中…")

        def worker():
            path = find_ghostscript(self.manual_gs, verbose=True)
            if path:
                try:
                    r = subprocess.run(
                        [path, "-h"], capture_output=True, text=True, timeout=10,
                        creationflags=(subprocess.CREATE_NO_WINDOW
                                       if sys.platform.startswith("win") else 0),
                    )
                    ver_line = ""
                    for line in (r.stdout or "").splitlines():
                        if "Ghostscript" in line or "GPL" in line:
                            ver_line = line.strip()
                            break
                    msg = f"✔ {path}"
                    if ver_line:
                        msg += f"   [{ver_line[:60]}]"
                except Exception as e:
                    msg = f"⚠ 找到 {path}，但执行失败: {e}"
                self.msg_queue.put(("gs", msg))
            else:
                self.msg_queue.put(("gs",
                    "✘ 未找到。点“手动指定”选择 gswin64c.exe"))

        threading.Thread(target=worker, daemon=True).start()

    def _pick_gs_manual(self):
        if sys.platform.startswith("win"):
            ft = [("Ghostscript", "gswin64c.exe gswin32c.exe gs.exe"),
                  ("所有文件", "*.*")]
        else:
            ft = [("所有文件", "*.*")]
        p = filedialog.askopenfilename(title="选择 gswin64c.exe", filetypes=ft)
        if p:
            self.manual_gs = p
            self._detect_gs_async()

    # ---------- 文件 ----------
    def _setup_dnd(self):
        if not HAS_DND:
            self.tree.insert("", "end", values=(
                "（未安装 tkinterdnd2，拖拽不可用）", "", "", ""))
            return
        try:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", self._on_drop)
        except Exception as e:
            print("拖拽注册失败:", e)

    def _choose_outdir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.outdir_var.set(d)

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择 PDF 文件",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")])
        self._append_files(paths)

    def _add_folder(self):
        d = filedialog.askdirectory(title="选择包含 PDF 的文件夹")
        if not d:
            return
        paths = [str(p) for p in Path(d).rglob("*.pdf")]
        if not paths:
            messagebox.showinfo("提示", "未找到 PDF 文件")
            return
        self._append_files(paths)

    def _on_drop(self, event):
        try:
            items = self.root.tk.splitlist(event.data)
        except Exception:
            items = [event.data]

        pdfs = []
        for it in items:
            p = Path(it)
            if p.is_dir():
                pdfs.extend(str(x) for x in p.rglob("*.pdf"))
            elif p.suffix.lower() == ".pdf":
                pdfs.append(str(p))
        if pdfs:
            self._append_files(pdfs)
            self.status_var.set(f"拖入 {len(pdfs)} 个 PDF")
        else:
            self.status_var.set("拖入的内容里没有 PDF")

    def _append_files(self, paths):
        existing = {f["path"] for f in self.files}
        added = skipped = 0
        for p in paths:
            try:
                p = str(Path(p).resolve())
            except Exception:
                continue
            if p in existing:
                continue
            stem = Path(p).stem.lower()
            if stem.endswith("_compressed") or "_compressed_" in stem:
                skipped += 1
                continue
            try:
                kb = os.path.getsize(p) / 1024
            except OSError:
                continue
            self.files.append({"path": p, "orig": kb, "new": None})
            self.tree.insert("", "end", iid=p, values=(
                os.path.basename(p), self._fmt_kb(kb), "待处理", ""))
            existing.add(p)
            added += 1

        msg = f"已添加 {added} 个文件"
        if skipped:
            msg += f"（跳过 {skipped} 个疑似已压缩）"
        if added or skipped:
            self.status_var.set(msg)

    def _remove_selected(self):
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.files = [f for f in self.files if f["path"] != iid]
        self.status_var.set(f"剩余 {len(self.files)} 个文件")

    def _clear_list(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("提示", "正在压缩中")
            return
        self.tree.delete(*self.tree.get_children())
        self.files.clear()
        self.status_var.set("列表已清空")

    def _open_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        path = sel[0]
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    # ---------- 图片统计 ----------
    def _show_image_stats(self):
        if not self.files:
            messagebox.showinfo("提示", "请先添加 PDF 文件")
            return
        if self.worker and self.worker.is_alive():
            return

        self.status_var.set("正在统计图片…")

        def worker():
            lines = []
            no_img = 0
            for f in self.files[:50]:
                n, max_side = pdf_image_stats(f["path"])
                name = os.path.basename(f["path"])
                if n == 0:
                    no_img += 1
                    lines.append(f"{name}: 无内嵌图片")
                else:
                    lines.append(f"{name}: {n} 张图, 最大边 {max_side}px")
            msg = "\n".join(lines[:20])
            if len(lines) > 20:
                msg += f"\n…（共 {len(lines)} 个）"
            if no_img:
                msg += (f"\n\n⚠ 有 {no_img} 个 PDF 不含内嵌图片，"
                        "标准压缩收益极小，建议改用“整页栅格化”模式。")
            self.msg_queue.put(("stats", msg))

        threading.Thread(target=worker, daemon=True).start()

    # ---------- 压缩 ----------
    def _collect_params(self):
        return {
            "quality":     self.quality_var.get().split()[0],
            "mode":        self._current_mode(),
            "use_pikepdf": bool(self.pikepdf_var.get()),
            "color_dpi":   int(self.color_dpi_var.get()),
            "gray_dpi":    int(self.gray_dpi_var.get()),
            "mono_dpi":    int(self.mono_dpi_var.get()),
            "jpeg_q":      int(self.jpeg_q_var.get()),
            "grayscale":   bool(self.grayscale_var.get()),
            "max_dim":     int(self.max_dim_var.get()),
            "pikepdf_q":   int(self.pikepdf_q_var.get()),
            "raster_dpi":  int(self.raster_dpi_var.get()),
        }

    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo("提示", "请先添加 PDF 文件")
            return

        gs = get_gs_path()
        if not gs:
            if messagebox.askyesno(
                "缺少 Ghostscript",
                "未找到 Ghostscript。\n\n是否手动指定 gswin64c.exe？"):
                self._pick_gs_manual()
            return

        suspicious = [f for f in self.files
                      if "_compressed" in Path(f["path"]).stem.lower()]
        if suspicious:
            if not messagebox.askyesno(
                "检测到已压缩文件",
                f"列表中有 {len(suspicious)} 个文件名带 '_compressed'，"
                "可能已经压过。\n再次压缩收益极低，且会损失画质。\n\n"
                "确定继续吗？"):
                return

        self.cancel_flag = False
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress.config(maximum=len(self.files), value=0)

        params = self._collect_params()
        params["outdir"] = self.outdir_var.get().strip()
        params["overwrite"] = self.overwrite_var.get()

        self.worker = threading.Thread(
            target=self._run_batch, args=(params,), daemon=True)
        self.worker.start()

    def _cancel(self):
        self.cancel_flag = True
        self.status_var.set("正在取消…")

    def _run_batch(self, params):
        total = len(self.files)
        done = success = failed = kept_count = 0

        for idx, item in enumerate(self.files):
            if self.cancel_flag:
                self.msg_queue.put(("status", f"已取消（完成 {done}/{total}）"))
                break

            src = Path(item["path"])
            out_dir = Path(params["outdir"]) if params["outdir"] else src.parent
            dst = out_dir / f"{src.stem}_compressed.pdf"

            if dst.exists() and not params["overwrite"]:
                i = 1
                while True:
                    cand = out_dir / f"{src.stem}_compressed_{i}.pdf"
                    if not cand.exists():
                        dst = cand
                        break
                    i += 1

            self.msg_queue.put(("row", (item["path"], "压缩中…", "")))
            self.msg_queue.put(("status",
                f"({idx+1}/{total}) 正在压缩: {src.name}"))

            try:
                orig_kb, new_kb, kept, mode = compress_one(src, dst, params)
                ratio = (1 - new_kb / orig_kb) * 100 if orig_kb > 0 else 0

                if kept:
                    tag = "（无压缩，保持原文件）"
                    kept_count += 1
                    status_txt = "◐ 未变"
                else:
                    tag = "（栅格化）" if mode == "raster" else ""
                    status_txt = "✔ 完成"

                self.msg_queue.put(("row", (
                    item["path"], status_txt,
                    f"{self._fmt_kb(new_kb)}  (-{ratio:.0f}%){tag}")))
                success += 1
            except Exception as e:
                print(f"[ERROR] {src}\n{e}\n")
                self.msg_queue.put(("row", (
                    item["path"], "✘ 失败", str(e)[:80])))
                failed += 1

            done += 1
            self.msg_queue.put(("progress", done))

        if not self.cancel_flag:
            extra = f"，其中 {kept_count} 个未变小（保留原文件）" if kept_count else ""
            self.msg_queue.put(("status",
                f"完成：成功 {success}，失败 {failed}，共 {total}{extra}"))
        self.msg_queue.put(("done", None))

    # ---------- 队列轮询 ----------
    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "row":
                    path, status, result = payload
                    if self.tree.exists(path):
                        vals = list(self.tree.item(path, "values"))
                        vals[2], vals[3] = status, result
                        self.tree.item(path, values=vals)
                elif kind == "progress":
                    self.progress.config(value=payload)
                elif kind == "status":
                    self.status_var.set(payload)
                elif kind == "gs":
                    self.gs_var.set(payload)
                elif kind == "stats":
                    messagebox.showinfo("图片统计", payload)
                elif kind == "done":
                    self.start_btn.config(state="normal")
                    self.cancel_btn.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    @staticmethod
    def _fmt_kb(kb):
        return f"{kb/1024:.2f} MB" if kb >= 1024 else f"{kb:.1f} KB"


def main():
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    PDFCompressorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()