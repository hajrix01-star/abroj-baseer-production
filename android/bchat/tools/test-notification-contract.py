#!/usr/bin/env python3
"""Run production display contract and durable claim logic with narrow JVM adapters."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
runtime = ROOT / 'artifacts/test-runtime'
runtime.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='notification-contract-', dir=runtime) as folder:
    target = Path(folder)
    stubs = {
        'android/content/Context.java': '''package android.content;
public abstract class Context {public static final int MODE_PRIVATE=0;
public abstract Context getApplicationContext();
public abstract SharedPreferences getSharedPreferences(String name,int mode);}''',
        'android/content/SharedPreferences.java': '''package android.content;
import java.util.Set;
public interface SharedPreferences {Set<String> getStringSet(String key,Set<String> fallback);Editor edit();
interface Editor {Editor putStringSet(String key,Set<String> value);boolean commit();}}''',
    }
    for name, text in stubs.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    sources = [*target.rglob('*.java'), ROOT / 'tests/NotificationPresentationContractTest.java',
               *(ROOT / f'app/src/main/java/com/baseer/freshchat/{name}.java'
                 for name in ('NotificationPresentation', 'BChatNotificationLedger'))]
    subprocess.run([shutil.which('javac') or 'javac', '-encoding', 'UTF-8', '-d', str(target),
                    *map(str, sources)], check=True)
    subprocess.run([shutil.which('java') or 'java', '-cp', str(target),
                    'com.baseer.freshchat.NotificationPresentationContractTest'], check=True)
