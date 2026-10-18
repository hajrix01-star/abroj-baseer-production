#!/usr/bin/env python3
"""Standalone Android35 receipt details component checks, not a product APK.

Actual native Activity/Dialog/JSONObject and locale preferences are used. The session
Host and all HTTP-shaped replies are declared fakes. No delivery/ACK/FCM/SQLite claim.
"""
from pathlib import Path
from contextlib import contextmanager
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
parser.add_argument("--selection", choices=("all", "display-time", "display-time-middle"), default="all")
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
output.mkdir(parents=True, exist_ok=False)
archived = output / "inputs"
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
         "LocalSettings", "LocalSettingsPolicy", "BChatReceiptDetailsPanel", "ReceiptDetailsProtocol", "BChatDisplayTime")
source = root / "app/src/main/java/com/baseer/freshchat"
production = [source / (name + ".java") for name in names]
production += [source / "sync/AccountScope.java", source / "sync/OutboxPolicy.java"]
tests = root / "tests/receipt-details-android"
resources = sorted(path for path in (root / "app/src/main/res").rglob("*") if path.is_file())
inputs = production + resources + sorted(tests.rglob("*.java")) + [tests / "AndroidManifest.xml", Path(__file__).resolve()]
hashes = {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
for path in inputs:
    destination = archived / path.relative_to(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(path.read_bytes())
frozen_jar = archived / "sdk/android-35.jar"
frozen_jar.parent.mkdir(parents=True, exist_ok=True)
frozen_jar.write_bytes(jar.read_bytes())
hashes["sdk/android-35.jar"] = hashlib.sha256(frozen_jar.read_bytes()).hexdigest()
(output / "source-manifest.json").write_text(json.dumps({"schema": 1, "source_sha256": hashes,
    "source_origins": {name: "installed-sdk35" if name == "sdk/android-35.jar" else "captured-live-exact-component-input" for name in hashes},
    "compile_from_archived_inputs": True, "selection": args.selection, "android_jar_sha256": hashes["sdk/android-35.jar"],
    "scope": "Native test Activity/Dialog/JSONObject/SharedPreferences locale; fake Host; no real HTTP/ACK/FCM/SQLite"},
    ensure_ascii=False, indent=2), encoding="utf-8")

def verify_inputs():
    live = {path.relative_to(root).as_posix(): path for path in inputs}
    live["sdk/android-35.jar"] = jar
    records = [{"path": name, "expected": expected,
                "live": hashlib.sha256(live[name].read_bytes()).hexdigest(),
                "archived": hashlib.sha256((archived / name).read_bytes()).hexdigest()} for name, expected in hashes.items()]
    matched = all(row["expected"] == row["live"] == row["archived"] for row in records)
    (output / "source-verification.json").write_text(json.dumps({"all_matched": matched, "inputs": records}, indent=2), encoding="utf-8")
    if not matched:
        raise SystemExit("Live/archive/SDK input changed; no frozen-source acceptance")

verify_inputs()

@contextmanager
def verified_inputs():
    try:
        yield
    finally:
        verify_inputs()

with verified_inputs(), tempfile.TemporaryDirectory(prefix="build-", dir=output) as temporary:
    build = Path(temporary)
    classes, dex, generated = build / "classes", build / "dex", build / "generated"
    for folder in (classes, dex, generated):
        folder.mkdir()
    run(bt / ("aapt2" + exe), "compile", "--dir", archived / "app/src/main/res", "-o", build / "resources.zip")
    run(bt / ("aapt2" + exe), "link", "-o", build / "base.apk", "-I", frozen_jar,
        "--manifest", archived / tests.relative_to(root) / "AndroidManifest.xml", build / "resources.zip",
        "--java", generated, "--custom-package", "com.baseer.freshchat")
    run(javac, "-encoding", "UTF-8", "-source", "8", "-target", "8", "-Xlint:-options",
        "-cp", frozen_jar, "-d", classes, *generated.rglob("*.java"), *[archived / path.relative_to(root) for path in production], *(archived / tests.relative_to(root)).rglob("*.java"))
    verify_inputs()
    with zipfile.ZipFile(build / "classes.jar", "w", zipfile.ZIP_DEFLATED) as archive:
        for item in classes.rglob("*.class"):
            archive.write(item, str(item.relative_to(classes)).replace("\\", "/"))
    run(bt / ("d8" + batch), "--min-api", "26", "--lib", frozen_jar, "--output", dex, build / "classes.jar")
    with zipfile.ZipFile(build / "base.apk", "a", zipfile.ZIP_DEFLATED) as archive:
        for item in dex.glob("*.dex"):
            archive.write(item, item.name)
    run(bt / ("zipalign" + exe), "-f", "4", build / "base.apk", build / "aligned.apk")
    apk = output / "BChat-standalone-receipt-details-tests.apk"
    run(bt / ("apksigner" + batch), "sign", "--ks", key, "--ks-key-alias", "bchat-preview",
        "--ks-pass", "file:" + str(password_file), "--out", apk, build / "aligned.apk")
    run(bt / ("apksigner" + batch), "verify", apk)
    apk_hash = hashlib.sha256(apk.read_bytes()).hexdigest()
    (output / "apk.json").write_text(json.dumps({"sha256": apk_hash, "package": PACKAGE, "product_apk": False}, indent=2), encoding="utf-8")
    verify_inputs()
    print("Standalone receipt details test APK verified; no product APK built or modified", flush=True)
    if args.run:
        adb = sdk / ("platform-tools/adb" + exe)
        run(adb, "-s", args.serial, "install", "-r", apk)
        if "Success" not in run(adb, "-s", args.serial, "shell", "pm", "clear", PACKAGE):
            raise SystemExit("Disposable package reset failed")
        result = run(adb, "-s", args.serial, "shell", "am", "instrument", "-w", "-r", "-e", "disposable", "true",
                     "-e", "selection", args.selection,
                     PACKAGE + "/com.baseer.freshchat.ReceiptDetailsInstrumentation", timeout=120)
        (output / "instrumentation.log").write_text(result, encoding="utf-8")
        captures = output / "captures"
        captures.mkdir(exist_ok=True)
        frame_names = [f"receipt-details-{language}-{mode}-{scale}-{position}.png"
                       for language in ("ar", "en") for mode in ("light", "dark")
                       for scale in ("1.0", "2.0") for position in ("top", "bottom")]
        if args.selection == "display-time":
            frame_names = [f"receipt-details-{language}-dark-2.0-{position}.png" for language in ("ar", "en") for position in ("top", "bottom")]
        elif args.selection == "display-time-middle":
            frame_names = [f"receipt-details-{language}-dark-2.0-middle.png" for language in ("ar", "en")]
        for name in ["receipt-details-results.json"] + frame_names:
            destination = output / name if name.endswith(".json") else captures / name
            captured = subprocess.run([str(adb), "-s", args.serial, "exec-out", "run-as", PACKAGE, "cat", "files/" + name],
                                      capture_output=True, timeout=15)
            if captured.returncode == 0:
                destination.write_bytes(captured.stdout)
        print(result)
        verify_inputs()
        if hashlib.sha256(apk.read_bytes()).hexdigest() != apk_hash:
            raise SystemExit("Standalone APK changed during component test")
        evidence = json.loads((output / "receipt-details-results.json").read_text(encoding="utf-8"))
        summary = ("PASS 2 supplemental Android receipt middle renders;" if args.selection == "display-time-middle" else
                   "PASS 2 actual Android receipt time renders;" if args.selection == "display-time" else "PASS 8 actual Android receipt detail renders and 9 focused journeys")
        if not evidence.get("passed") or summary not in result or "INSTRUMENTATION_CODE: -1" not in result or evidence.get("selection") != args.selection:
            raise SystemExit("Receipt details checks failed; inspect preserved evidence and frames")
        focused = args.selection in ("display-time", "display-time-middle")
        if len(evidence.get("renders", [])) != (2 if focused else 8) or len(evidence.get("journeys", [])) != (0 if focused else 9):
            raise SystemExit("Incomplete receipt details evidence")
        if args.selection == "display-time":
            expected = {f"receipt-details-{language}-dark-2.0" for language in ("ar", "en")}
            if ({row.get("case") for row in evidence["renders"]} != expected or evidence.get("protocol_acceptances") != 0 or evidence.get("protocol_rejections") != 0
                    or not all(row.get("passed") is True and len(row.get("time_geometry_top", {}).get("timestamp_textviews", [])) == 2
                               and len(row.get("time_geometry_bottom", {}).get("timestamp_textviews", [])) == 2
                               and row["time_geometry_bottom"]["footer_global_visible"] is True
                               and row["time_geometry_bottom"]["footer_local_visible"] is True
                               and row["time_geometry_bottom"]["footer_transform_identity"] is True
                               and row["time_geometry_bottom"]["footer_full"] == row["time_geometry_bottom"]["footer_clipped"] for row in evidence["renders"])):
                raise SystemExit("Incomplete focused timestamp/layout/reachability evidence")
        elif args.selection == "display-time-middle":
            expected = {f"receipt-details-{language}-dark-2.0-middle" for language in ("ar", "en")}
            if ({row.get("case") for row in evidence["renders"]} != expected or evidence.get("protocol_acceptances") != 0 or evidence.get("protocol_rejections") != 0
                    or evidence.get("time_geometry_trace") != []
                    or not all(row.get("passed") is True and row.get("frames") == [row["case"] + ".png"]
                               and row.get("middle_geometry", {}).get("phase") == "after_native_scroll_and_preDraw"
                               and row["middle_geometry"]["transform_identity"] is True and row["middle_geometry"]["local_visible"] is True
                               and row["middle_geometry"]["layout_present"] is True and row["middle_geometry"]["ellipsize_is_null"] is True
                               and row["middle_geometry"]["full_rect_screen"] == row["middle_geometry"]["clipped_rect_screen"] for row in evidence["renders"])):
                raise SystemExit("Incomplete supplemental actual timestamp visibility/Layout evidence")
            trace = evidence.get("time_middle_trace", [])
            if (len(trace) != 4 or [row.get("phase") for row in trace] != ["before_native_scroll", "after_native_scroll_and_preDraw"] * 2
                    or [row.get("language") for row in trace] != ["ar", "ar", "en", "en"]):
                raise SystemExit("Incomplete middle-only native trace inventory")
        for name in frame_names:
            frame = captures / name
            if not frame.is_file() or not frame.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                raise SystemExit("Missing actual native frame: " + name)
        print("Captured 2 supplemental middle Dialog-decor frames plus actual entire timestamp visibility/Layout, no top/bottom/old journeys" if args.selection == "display-time-middle" else
              "Captured 4 actual Dialog-decor frames plus native text/layout/reachability, 2 configurations, no old journeys" if focused else "Captured 16 actual Dialog-decor frames, 8 configurations and 9 journeys")
