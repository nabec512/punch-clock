# PyInstaller build definition. Run through packaging\build.ps1.
# A folder build is used rather than one file: it starts faster and is less
# likely to be flagged by antivirus software.
from pathlib import Path

root = Path(SPECPATH).parent

analysis = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root / "src")],
    excludes=["pytest", "_pytest", "setuptools", "pip"],
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PunchClock",
    console=False,
    upx=False,
)
COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    upx=False,
    name="PunchClock",
)
