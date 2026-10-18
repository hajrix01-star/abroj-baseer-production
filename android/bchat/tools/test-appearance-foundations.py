#!/usr/bin/env python3
"""Production grapheme logic + semantic-palette contrast. No device rendering claim."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
java_home = Path(os.environ.get("JAVA_HOME", r"C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot")) / "bin"
java = shutil.which("java") or str(java_home / "java.exe")
javac = shutil.which("javac") or str(java_home / "javac.exe")
runtime = ROOT / "artifacts" / "test-runtime"
runtime.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="appearance-", dir=runtime) as scratch:
    sources = [ROOT / "app/src/main/java/com/baseer/freshchat/AvatarInitials.java",
               ROOT / "tests/AvatarInitialsTest.java",
               ROOT / "app/src/main/java/com/baseer/freshchat/MediaRights.java",
               ROOT / "tests/MediaRightsTest.java"]
    subprocess.run([javac, "-encoding", "UTF-8", "-d", scratch,
                    *map(str, sources)], check=True)
    subprocess.run([java, "-cp", scratch,
                    "com.baseer.freshchat.AvatarInitialsTest"], check=True)
    subprocess.run([java, "-cp", scratch,
                    "com.baseer.freshchat.MediaRightsTest"], check=True)


def luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    rgb = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return sum(a * b for a, b in zip(rgb, (.2126, .7152, .0722)))


checks = 0
for mode in ("values", "values-night"):
    colors = {item.attrib["name"]: item.text for item in ET.parse(
        ROOT / "app/src/main/res" / mode / "chat_colors.xml").getroot()}
    for foreground in ("bchat_ink", "bchat_muted"):
        for surface in ("bchat_surface", "bchat_canvas", "bchat_sent", "bchat_received"):
            bright, dark = sorted((luminance(colors[foreground]), luminance(colors[surface])), reverse=True)
            ratio = (bright + .05) / (dark + .05)
            assert ratio >= 4.5, (mode, foreground, surface, ratio)
            checks += 1
    bright, dark = sorted((luminance(colors["bchat_accent"]), luminance(colors["bchat_surface"])), reverse=True)
    assert (bright + .05) / (dark + .05) >= 4.5
    checks += 1
print(f"PASS {checks} day/night normal-text contrast checks; font-scale/layout require Android")
