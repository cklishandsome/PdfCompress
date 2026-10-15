# build.py
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "PDFCompressor"
ICON = "icon.ico"

def clean():
    for d in ("build", "dist"):
        if Path(d).exists():
            shutil.rmtree(d)
    spec = Path(f"{APP_NAME}.spec")
    # 保留你自己手改过的 spec，不删
    # if spec.exists(): spec.unlink()

def main():
    clean()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        f"{APP_NAME}.spec",
    ]
    print("运行:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    exe = Path("dist") / f"{APP_NAME}.exe"
    if exe.exists():
        print(f"\n✅ 打包完成: {exe.resolve()}")
        print(f"   大小: {exe.stat().st_size/1024/1024:.1f} MB")
    else:
        print("❌ 未找到 exe，检查日志")
        sys.exit(1)

if __name__ == "__main__":
    main()