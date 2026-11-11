# PyInstaller build recipe: `pyinstaller imuviz.spec --noconfirm`
# Produces dist/IMU-Visualiser/ (and dist/IMU-Visualiser.app on macOS).
import sys

from PyInstaller.utils.hooks import collect_submodules

# pyserial picks its port-listing backend per OS with conditional imports;
# bundle all of them so a build never depends on which OS analysed it.
hiddenimports = collect_submodules("serial.tools")

a = Analysis(
    ["main.py"],
    pathex=["."],
    hiddenimports=hiddenimports,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IMU-Visualiser",
    console=False,
    upx=False,  # UPX-packed binaries trip antivirus heuristics
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="IMU-Visualiser",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="IMU-Visualiser.app",
        bundle_identifier="io.github.clawntl.imu-visualiser",
    )
