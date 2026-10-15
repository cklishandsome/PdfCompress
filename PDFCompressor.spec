# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---- tkinterdnd2：收集它的 tcl 数据文件 ----
dnd_datas = collect_data_files('tkinterdnd2')

# ---- 如果图标存在才加 ----
import os
icon_path = 'icon.ico' if os.path.exists('icon.ico') else None


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas = dnd_datas + [
            ('gs', 'gs'),          # 把 gs 目录整体打进 exe
        ],                       # ← tkdnd 的 dll/tcl
    hiddenimports=[
        'pikepdf',
        'PIL',
        'PIL.Image',
        'PIL.ImageFile',
        'tkinterdnd2',
    ] + collect_submodules('tkinterdnd2'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除没用的大库，减小体积
    excludes=[
        'matplotlib', 'numpy', 'scipy', 'pandas',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'IPython', 'jupyter', 'notebook',
        'test', 'unittest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDFCompressor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                  # 用 upx 压缩（需先安装 upx，见下文）
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # ← 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,            # ← 图标（没有则为 None）
)