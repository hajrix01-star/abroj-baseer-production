#!/usr/bin/env python3
"""Real Android EXIF/codec tests and ownership tests with injected external focus results.

Builds only a standalone package. Offline attachment/import types are declared compile
adapters restricted to synthetic private fixtures; connected decoding uses production code.
"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument("--run", action="store_true")
parser.add_argument("--serial", default="emulator-5580")
args = parser.parse_args()
if not args.serial.startswith("emulator-") or not args.serial[9:].isdigit():
    raise SystemExit("Only a disposable emulator is accepted")
root = Path(__file__).resolve().parents[1]
sdk = Path(os.environ.get("ANDROID_HOME", "D:/Codex/AndroidSdk"))
bt = sdk / "build-tools/35.0.0"
jar = sdk / "platforms/android-35/android.jar"
java_home = Path(os.environ.get("JAVA_HOME", r"C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot"))
javac = shutil.which("javac") or str(java_home / "bin/javac.exe")
exe = ".exe" if os.name == "nt" else ""
batch = ".bat" if os.name == "nt" else ""
output = root / "artifacts/media-android"
output.mkdir(parents=True, exist_ok=True)
key = Path(os.environ["BCHAT_SIGNING_KEY"])
password_file = Path(os.environ["BCHAT_SIGNING_PASSWORD_FILE"])
if not key.is_file() or not password_file.is_file():
    raise SystemExit("Existing approved signing paths required; no key is generated")


def run(*command):
    result = subprocess.run([str(item) for item in command], text=True, encoding="utf-8",
                            errors="replace", capture_output=True)
    with (output / "build.log").open("a", encoding="utf-8") as log:
        log.write(Path(str(command[0])).name + "\n" + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        raise SystemExit(f"{Path(str(command[0])).name} failed ({result.returncode}); see build.log")


with tempfile.TemporaryDirectory(prefix="build-", dir=output) as temporary:
    build = Path(temporary)
    classes, dex = build / "classes", build / "dex"
    classes.mkdir()
    dex.mkdir()
    run(bt / ("aapt2" + exe), "link", "-o", build / "base.apk", "-I", jar,
        "--manifest", root / "tests/android-media/AndroidManifest.xml")
    names = ("ImagePreviews", "ImagePreviewPolicy", "AudioFocusLease", "ZoomableImageView",
             "AudioPlayback", "PlaybackState", "AudioDiagnostic")
    source = root / "app/src/main/java/com/baseer/freshchat"
    run(javac, "-encoding", "UTF-8", "-source", "8", "-target", "8", "-Xlint:-options",
        "-cp", jar, "-d", classes, *(source / (name + ".java") for name in names),
        *(root / "tests/android-media").rglob("*.java"))
    run(bt / ("d8" + batch), "--min-api", "26", "--lib", jar, "--output", dex, *classes.rglob("*.class"))
    with zipfile.ZipFile(build / "base.apk", "a", zipfile.ZIP_DEFLATED) as archive:
        for item in dex.glob("*.dex"):
            archive.write(item, item.name)
    run(bt / ("zipalign" + exe), "-f", "4", build / "base.apk", build / "aligned.apk")
    apk = output / "BChat-standalone-media-tests.apk"
    run(bt / ("apksigner" + batch), "sign", "--ks", key, "--ks-key-alias", "bchat-preview",
        "--ks-pass", "file:" + str(password_file), "--out", apk, build / "aligned.apk")
    run(bt / ("apksigner" + batch), "verify", apk)
    print("Standalone media test APK verified; no product APK built or modified", flush=True)
    if args.run:
        adb = sdk / ("platform-tools/adb" + exe)
        run(adb, "-s", args.serial, "install", "-r", apk)
        result = subprocess.run([str(adb), "-s", args.serial, "shell", "am", "instrument", "-w", "-r",
                                 "-e", "disposable", "true",
                                 "com.baseer.bchat.media.test/com.baseer.freshchat.MediaInstrumentation"],
                                text=True, encoding="utf-8", errors="replace", capture_output=True, check=True)
        (output / "instrumentation.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        print(result.stdout)
        if "PASS actual Android EXIF/decoding and audio ownership:" not in result.stdout or "INSTRUMENTATION_CODE: -1" not in result.stdout:
            raise SystemExit("Media instrumentation failed; inspect its actual output")
