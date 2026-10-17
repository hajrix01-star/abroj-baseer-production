#!/usr/bin/env python3
"""Standalone Android35 receipt details component checks, not a product APK.

Actual native Activity/Dialog/JSONObject and locale preferences are used. The session
Host and all HTTP-shaped replies are declared fakes. No delivery/ACK/FCM/SQLite claim.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

PACKAGE = "com.baseer.bchat.receipt.details.test"
parser = argparse.ArgumentParser()
parser.add_argument("--run", action="store_true")
parser.add_argument("--serial", default="emulator-5580")
parser.add_argument("--label", default="", help="Isolated evidence subfolder; earlier runs are preserved")
args = parser.parse_args()
if args.serial != "emulator-5580":
    raise SystemExit("Only the authorized existing emulator-5580 is accepted")
if args.label and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", args.label):
    raise SystemExit("Unsafe evidence label")
root = Path(__file__).resolve().parents[1]
sdk = Path(os.environ.get("ANDROID_HOME", "D:/Codex/AndroidSdk"))
bt = sdk / "build-tools/35.0.0"
jar = sdk / "platforms/android-35/android.jar"
java_home = Path(os.environ.get("JAVA_HOME", r"C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot"))
javac = shutil.which("javac") or str(java_home / "bin/javac.exe")
exe = ".exe" if os.name == "nt" else ""
batch = ".bat" if os.name == "nt" else ""
output = root / "artifacts/receipt-details-android"
if args.label:
    output /= args.label
output.mkdir(parents=True, exist_ok=True)
approved = Path(os.environ.get("LOCALAPPDATA", "")) / "Baseer/BChatSigning/fresh-install-20261009"
key = Path(os.environ.get("BCHAT_SIGNING_KEY", str(approved / "bchat-preview-fresh.p12")))
password_file = Path(os.environ.get("BCHAT_SIGNING_PASSWORD_FILE", str(approved / "keystore.password")))
if not key.is_file() or not password_file.is_file():
    raise SystemExit("Existing documented signing paths required; no key is generated or read by this tool")


def run(*command, timeout=90):
    result = subprocess.run([str(item) for item in command], text=True, encoding="utf-8",
                            errors="replace", capture_output=True, timeout=timeout)
    with (output / "build.log").open("a", encoding="utf-8") as log:
        log.write(Path(str(command[0])).name + "\n" + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        raise SystemExit(f"{Path(str(command[0])).name} failed ({result.returncode}); see build.log")
    return result.stdout


names = ("Ui", "UiPalette", "ChatAppearance", "AvatarInitials", "AppLocale", "AppLocalePolicy",
         "LocalSettings", "LocalSettingsPolicy", "BChatReceiptDetailsPanel", "ReceiptDetailsProtocol")
source = root / "app/src/main/java/com/baseer/freshchat"
production = [source / (name + ".java") for name in names]
production += [source / "sync/AccountScope.java", source / "sync/OutboxPolicy.java"]
tests = root / "tests/receipt-details-android"
resources = sorted(path for path in (root / "app/src/main/res").rglob("*") if path.is_file())
inputs = production + resources + sorted(tests.rglob("*.java")) + [tests / "AndroidManifest.xml", Path(__file__).resolve()]
hashes = {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
(output / "source-manifest.json").write_text(json.dumps({"schema": 1, "source_sha256": hashes,
    "scope": "Native test Activity/Dialog/JSONObject/SharedPreferences locale; fake Host; no real HTTP/ACK/FCM/SQLite"},
    ensure_ascii=False, indent=2), encoding="utf-8")

with tempfile.TemporaryDirectory(prefix="build-", dir=output) as temporary:
    build = Path(temporary)
    classes, dex, generated = build / "classes", build / "dex", build / "generated"
    for folder in (classes, dex, generated):
        folder.mkdir()
    run(bt / ("aapt2" + exe), "compile", "--dir", root / "app/src/main/res", "-o", build / "resources.zip")
    run(bt / ("aapt2" + exe), "link", "-o", build / "base.apk", "-I", jar,
        "--manifest", tests / "AndroidManifest.xml", build / "resources.zip",
        "--java", generated, "--custom-package", "com.baseer.freshchat")
    run(javac, "-encoding", "UTF-8", "-source", "8", "-target", "8", "-Xlint:-options",
        "-cp", jar, "-d", classes, *generated.rglob("*.java"), *production, *tests.rglob("*.java"))
    with zipfile.ZipFile(build / "classes.jar", "w", zipfile.ZIP_DEFLATED) as archive:
        for item in classes.rglob("*.class"):
            archive.write(item, str(item.relative_to(classes)).replace("\\", "/"))
    run(bt / ("d8" + batch), "--min-api", "26", "--lib", jar, "--output", dex, build / "classes.jar")
    with zipfile.ZipFile(build / "base.apk", "a", zipfile.ZIP_DEFLATED) as archive:
        for item in dex.glob("*.dex"):
            archive.write(item, item.name)
    run(bt / ("zipalign" + exe), "-f", "4", build / "base.apk", build / "aligned.apk")
    apk = output / "BChat-standalone-receipt-details-tests.apk"
    run(bt / ("apksigner" + batch), "sign", "--ks", key, "--ks-key-alias", "bchat-preview",
        "--ks-pass", "file:" + str(password_file), "--out", apk, build / "aligned.apk")
    run(bt / ("apksigner" + batch), "verify", apk)
    print("Standalone receipt details test APK verified; no product APK built or modified", flush=True)
    if args.run:
        adb = sdk / ("platform-tools/adb" + exe)
        run(adb, "-s", args.serial, "install", "-r", apk)
        result = run(adb, "-s", args.serial, "shell", "am", "instrument", "-w", "-r", "-e", "disposable", "true",
                     PACKAGE + "/com.baseer.freshchat.ReceiptDetailsInstrumentation", timeout=120)
        (output / "instrumentation.log").write_text(result, encoding="utf-8")
        captures = output / "captures"
        captures.mkdir(exist_ok=True)
        frame_names = [f"receipt-details-{language}-{mode}-{scale}-{position}.png"
                       for language in ("ar", "en") for mode in ("light", "dark")
                       for scale in ("1.0", "2.0") for position in ("top", "bottom")]
        for name in ["receipt-details-results.json"] + frame_names:
            destination = output / name if name.endswith(".json") else captures / name
            captured = subprocess.run([str(adb), "-s", args.serial, "exec-out", "run-as", PACKAGE, "cat", "files/" + name],
                                      capture_output=True, timeout=15)
            if captured.returncode == 0:
                destination.write_bytes(captured.stdout)
        print(result)
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != hashes[str(path.relative_to(root)).replace("\\", "/")]
               for path in inputs):
            raise SystemExit("Inputs changed during the component test; no frozen-source acceptance")
        evidence = json.loads((output / "receipt-details-results.json").read_text(encoding="utf-8"))
        if not evidence.get("passed") or "PASS 8 actual Android receipt detail renders and 9 focused journeys" not in result or "INSTRUMENTATION_CODE: -1" not in result:
            raise SystemExit("Receipt details checks failed; inspect preserved evidence and frames")
        if len(evidence.get("renders", [])) != 8 or len(evidence.get("journeys", [])) != 9:
            raise SystemExit("Incomplete receipt details evidence")
        for name in frame_names:
            frame = captures / name
            if not frame.is_file() or not frame.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                raise SystemExit("Missing actual native frame: " + name)
        print("Captured 16 actual Dialog-decor frames, 8 configurations and 9 journeys")
