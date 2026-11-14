# PyInstaller spec: `pyinstaller packaging/chartwright.spec` (run from the repository root)
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
datas = [(str(root / "data"), "data"), (str(root / "chartwright" / "static"), "chartwright/static")]
for pkg in ("rapidocr", "symspellpy"):
    datas += collect_data_files(pkg)            # OCR models + config, word-frequency list
hidden = collect_submodules("rapidocr") + ["cv2", "docx", "onnxruntime"]

a = Analysis([str(root / "packaging" / "entry.py")], pathex=[str(root)], datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "scipy", "IPython", "pytest"])
pyz = PYZ(a.pure)
icon = str(root / "tools" / ("icon.icns" if sys.platform == "darwin" else "icon.ico"))
if not Path(icon).exists():
    icon = None
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ChartWright", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="ChartWright")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="ChartWright.app", icon=icon, bundle_identifier="com.chartwright.app",
                 info_plist={"LSUIElement": True, "CFBundleName": "ChartWright", "CFBundleShortVersionString": "1.0.3",
                             "NSHighResolutionCapable": True})
