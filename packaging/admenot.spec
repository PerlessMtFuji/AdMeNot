# PyInstaller (onedir): AdMeNot.exe (okno) i admenot-cli.exe (konsola) ze wspólnym _internal.
# Uruchamia go scripts/build_release.py; ręcznie (Git Bash):
#   ADMENOT_VERSION=0.9.0 .venv/Scripts/python -m PyInstaller --noconfirm --clean \
#       --distpath dist --workpath build/pyinstaller packaging/admenot.spec
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent  # noqa: F821 — SPECPATH ustawia PyInstaller
SRC = ROOT / "src"
TOOLS = (SRC / "admenot" / "assets" / "tools").resolve()
ICON = SRC / "admenot" / "assets" / "icon" / "admenot.ico"
VERSION = os.environ["ADMENOT_VERSION"]
NUMBERS = (*(int(part) for part in VERSION.split(".")), 0)
PUBLISHER = "Eryk Wlodarski"


def version_info(description, internal_name):
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=NUMBERS, prodvers=NUMBERS),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", PUBLISHER),
                StringStruct("FileDescription", description),
                StringStruct("FileVersion", ".".join(map(str, NUMBERS))),
                StringStruct("InternalName", internal_name),
                StringStruct("LegalCopyright", f"Copyright (c) {PUBLISHER}"),
                StringStruct("OriginalFilename", f"{internal_name}.exe"),
                StringStruct("ProductName", "AdMeNot"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


# androguard nie ma hooka: bez public.xml analiza manifestu pada po cichu (próba pakowania)
datas = (collect_data_files("admenot", excludes=["**/__pycache__/**"])
         + collect_data_files("androguard"))

a = Analysis(
    [str(ROOT / "packaging" / "launch_gui.py"), str(ROOT / "packaging" / "launch_cli.py")],
    pathex=[str(SRC)],
    datas=datas,
    hiddenimports=collect_submodules("admenot"),
    excludes=["IPython", "jedi", "tkinter", "_tkinter"],  # IPython tylko w androguard/cli
)


def duplicate_tool(entry):
    """DLL-e scrcpy, które PyInstaller dokłada drugi raz do korzenia _internal."""
    dest, src, _kind = entry
    from_tools = Path(src).resolve().is_relative_to(TOOLS)
    return from_tools and Path(dest).parts[:3] != ("admenot", "assets", "tools")


a.binaries = [entry for entry in a.binaries if not duplicate_tool(entry)]
pyz = PYZ(a.pure)
gui = EXE(pyz, [s for s in a.scripts if s[0] != "launch_cli"], [], exclude_binaries=True,
          name="AdMeNot", console=False, icon=str(ICON),
          version=version_info("AdMeNot", "AdMeNot"))
cli = EXE(pyz, [s for s in a.scripts if s[0] != "launch_gui"], [], exclude_binaries=True,
          name="admenot-cli", console=True, icon=str(ICON),
          version=version_info("AdMeNot command line", "admenot-cli"))
coll = COLLECT(gui, cli, a.binaries, a.datas, name="AdMeNot")
