#!/usr/bin/env bash
# Public-API kernel DEX only: no app installation, signing key or emulator operation.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Existing official Android SDK is required}"
APP_CLASSES="${APP_CLASSES:-$PWD/artifacts/build/classes}"
JAR="$ANDROID_HOME/platforms/android-35/android.jar";D8="$ANDROID_HOME/build-tools/35.0.0/d8"
OUT="${OUT:-$PWD/artifacts/media-kernel-unsigned}"
[[ -f "$APP_CLASSES/com/baseer/bwork/legacy/ImagePreviews.class" ]] || { echo 'Current app classes are required.' >&2;exit 1; }
mkdir -p "$OUT/test-classes" "$OUT/dex"
find tests/android-media-kernel -name '*.java' | sort > "$OUT/test-sources.txt"
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$JAR:$APP_CLASSES" -d "$OUT/test-classes" @"$OUT/test-sources.txt"
# Include the unchanged current app dependencies; only MediaKernelMain is an entry point.
find "$APP_CLASSES" "$OUT/test-classes" -name '*.class' | sort > "$OUT/classes.txt"
"$D8" --min-api 26 --lib "$JAR" --output "$OUT/dex" @"$OUT/classes.txt"
python3 - "$OUT" "$APP_CLASSES" "$ANDROID_HOME" <<'PY'
import hashlib,json,pathlib,sys
out,classes,sdk=map(pathlib.Path,sys.argv[1:])
def record(path):return {'path':str(path),'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
root=pathlib.Path.cwd()
source=[root/'tests/android-media-kernel/com/baseer/bwork/legacy/MediaKernelMain.java',root/'tools/build-media-kernel.sh']
production=[root/'app/src/main/java/com/baseer/bwork/legacy'/name for name in ['AttachmentSupport.java','ImagePreviews.java','ImagePreviewPolicy.java','ChatStore.java']]
report={'status':'compiled_unsigned_dex_only_not_executed','entrypoint':'com.baseer.bwork.legacy.MediaKernelMain','test_sources':[record(p) for p in source],'frozen_production_sources':[record(p) for p in production],'dex':[record(p) for p in sorted((out/'dex').glob('*.dex'))],'compiled_inputs':[record(pathlib.Path(p)) for p in (out/'classes.txt').read_text().splitlines()],'android_jar':record(sdk/'platforms/android-35/android.jar'),'limits':['public native decoder only','no UI/provider/physical/signed-upgrade acceptance','no hidden API/runtime workaround']}
(out/'COMPILE-MANIFEST.json').write_text(json.dumps(report,indent=2)+'\n')
for item in report['dex']: print(item['sha256']+'  '+item['path'])
PY
echo 'Unsigned public-API kernel DEX compiled only. NOT installed or executed.'
