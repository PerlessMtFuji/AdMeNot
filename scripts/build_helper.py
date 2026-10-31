"""Buduje pomocnika telefonu: src/admenot/engine/transfer/helper_bin/{admenot-helper.dex, .apk, SHA256SUMS}.

    .venv\\Scripts\\python scripts\\build_helper.py [--keystore ŚCIEŻKA] [--javac ŚCIEŻKA]

Źródła: android/helper/. SDK z ANDROID_HOME, inaczej %LOCALAPPDATA%/Android/Sdk (najwyższe build-tools
i platforms/android-*/android.jar). JDK: --javac, JAVA_HOME, inaczej Eclipse Adoptium (javac z PATH
bywa zepsuty). Podpis kluczem z --keystore lub ADMENOT_HELPER_KEYSTORE (alias admenot-helper), hasło
z ADMENOT_HELPER_KS_PASS; klucz leży poza repo, obok klucza manifestu aktualizacji. Utworzenie klucza:

    keytool -genkeypair -keystore <ścieżka> -alias admenot-helper -keyalg RSA -keysize 3072 -validity 36500

Bez klucza powstaje tylko .dex, a SHA256SUMS zostaje bez zmian (kod wyjścia 3).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from admenot.engine.transfer import helper

SRC = ROOT / "android" / "helper"
OUT = helper.HELPER_BIN
ALIAS = "admenot-helper"
MIN_SDK, TARGET_SDK = 21, 35


class BuildError(Exception):
    pass


def _version_key(name: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", name))


def find_sdk() -> Path:
    env = os.environ.get("ANDROID_HOME")
    sdk = Path(env) if env else Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk"
    if not (sdk / "build-tools").is_dir():
        raise BuildError(f"Android SDK not found at {sdk} (set ANDROID_HOME)")
    return sdk


def find_build_tools(sdk: Path) -> Path:
    dirs = [d for d in (sdk / "build-tools").iterdir() if d.is_dir() and re.match(r"^\d", d.name)]
    if not dirs:
        raise BuildError("no build-tools in the SDK")
    return max(dirs, key=lambda d: _version_key(d.name))


def find_android_jar(sdk: Path) -> Path:
    jars = [p for p in (sdk / "platforms").glob("android-*/android.jar")]
    if not jars:
        raise BuildError("no platforms/android-*/android.jar in the SDK")
    return max(jars, key=lambda p: _version_key(p.parent.name))


def find_javac(explicit: str | None) -> Path:
    exe = "javac.exe" if sys.platform == "win32" else "javac"
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]) / "bin" / exe)
    found = glob.glob("C:/Program Files/Eclipse Adoptium/jdk-*/bin/javac.exe")
    candidates += sorted((Path(p) for p in found), key=lambda p: _version_key(p.parents[1].name),
                         reverse=True)
    for c in candidates:
        if c.is_file():
            return c
    raise BuildError("no working JDK: pass --javac or set JAVA_HOME")


def _tool(bt: Path, name: str) -> Path:
    for suffix in (".exe", ".bat", ""):
        p = bt / (name + suffix)
        if p.is_file():
            return p
    raise BuildError(f"{name} not found in {bt}")


def run(cmd: list[str | Path], **kw) -> None:
    proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, check=False,
                          **kw)
    if proc.returncode != 0:
        raise BuildError(f"{Path(str(cmd[0])).name} failed:\n{proc.stdout}\n{proc.stderr}")


def build_dex(javac: Path, bt: Path, jar: Path, work: Path) -> Path:
    classes = work / "classes"
    classes.mkdir()
    sources = sorted(str(p) for p in (SRC / "src").rglob("*.java"))
    run([javac, "-encoding", "UTF-8", "--release", "8", "-Xlint:-options", "-cp", jar, "-d", classes,
         *sources])
    class_files = sorted(str(p) for p in classes.rglob("*.class"))
    dex_dir = work / "dex"
    dex_dir.mkdir()
    run([_tool(bt, "d8"), "--release", "--min-api", str(MIN_SDK), "--lib", jar, "--output", dex_dir,
         *class_files])
    return dex_dir / "classes.dex"


def build_apk(bt: Path, jar: Path, dex: Path, work: Path, keystore: Path) -> Path:
    if not os.environ.get("ADMENOT_HELPER_KS_PASS"):
        raise BuildError("ADMENOT_HELPER_KS_PASS is not set")
    base = work / "base.apk"
    run([_tool(bt, "aapt2"), "link", "-o", base, "--manifest", SRC / "AndroidManifest.xml", "-I", jar,
         "--min-sdk-version", str(MIN_SDK), "--target-sdk-version", str(TARGET_SDK)])
    with zipfile.ZipFile(base, "a", zipfile.ZIP_DEFLATED) as z:
        z.write(dex, "classes.dex")
    aligned = work / "aligned.apk"
    run([_tool(bt, "zipalign"), "-f", "-p", "4", base, aligned])
    signed = work / "signed.apk"
    run([_tool(bt, "apksigner"), "sign", "--ks", keystore, "--ks-key-alias", ALIAS,
         "--ks-pass", "env:ADMENOT_HELPER_KS_PASS", "--key-pass", "env:ADMENOT_HELPER_KS_PASS",
         "--out", signed, aligned])
    run([_tool(bt, "apksigner"), "verify", signed])
    return signed


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_sums(out: Path) -> None:
    lines = [f"{_sha(out / n)}  {n}" for n in helper.ARTIFACTS.values()]
    lines.append(f"sources={helper.sources_digest(SRC)}")
    (out / helper.SUMS).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keystore", help="release keystore (default: ADMENOT_HELPER_KEYSTORE)")
    ap.add_argument("--javac", help="javac of a working JDK")
    args = ap.parse_args(argv)
    try:
        sdk = find_sdk()
        bt, jar, javac = find_build_tools(sdk), find_android_jar(sdk), find_javac(args.javac)
        print(f"build-tools {bt.name}, {jar.parent.name}, {javac}")
        OUT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="admenot-helper-build-") as tmp:
            work = Path(tmp)
            dex = build_dex(javac, bt, jar, work)
            shutil.copyfile(dex, OUT / helper.ARTIFACTS["dex"])
            print(f"{helper.ARTIFACTS['dex']}: {dex.stat().st_size} B")
            ks = args.keystore or os.environ.get("ADMENOT_HELPER_KEYSTORE")
            if not ks:
                print("no keystore (--keystore / ADMENOT_HELPER_KEYSTORE): APK and SHA256SUMS not written",
                      file=sys.stderr)
                return 3
            if not Path(ks).is_file():
                raise BuildError(f"keystore not found: {ks}")
            apk = build_apk(bt, jar, dex, work, Path(ks))
            shutil.copyfile(apk, OUT / helper.ARTIFACTS["apk"])
            print(f"{helper.ARTIFACTS['apk']}: {apk.stat().st_size} B")
        write_sums(OUT)
        print(f"{helper.SUMS} written")
        return 0
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
