#!/usr/bin/env python3
"""C26 isolated FULL production Activity after-C11 comparison; existing cached dependencies only.

Snapshots explicit-commit Git blobs byte-for-byte, excludes Firebase classes,
uses a test-only BuildConfig/manifest, never modifies or builds a product release. --run-built
requires the exclusive emulator AND host-heavy-tool measurement window granted by root.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile

PACKAGE='com.baseer.bchat.performance.test'
BASELINE='2570f3af16ba682c722039b29cf65376490a7c57'
SOURCE_PATHS=('android/bchat/app/src/main/java','android/bchat/app/src/main/res',
              'android/bchat/tests/performance-android','android/bchat/tools/test-performance-android.py')
INPUT_TREES=('project/app/src','frozen-inputs')
INPUT_CONFIGS=('project/build.gradle','project/settings.gradle','project/gradle.properties','project/app/build.gradle')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def require_build_source(expected,git_read):
    if git_read('rev-parse','HEAD')!=expected:raise SystemExit('Reviewed HEAD differs from explicit compiled commit')
    if git_read('diff','--name-only',expected,'--',*SOURCE_PATHS):raise SystemExit('Tracked compiled/test inputs changed during snapshot/build')


def snapshot_records(base):
    paths=[base/name for name in INPUT_CONFIGS]
    for name in INPUT_TREES:paths.extend(path for path in (base/name).rglob('*')if path.is_file())
    return {path.relative_to(base).as_posix():sha(path)for path in paths}


def verify_snapshot(base,expected):
    # Re-enumerate source/archive trees too: an extra source/resource must not enter compilation unnoticed.
    actual=snapshot_records(base)
    if actual!=expected:
        changed=sorted(path for path in set(actual)|set(expected)if actual.get(path)!=expected.get(path))
        raise SystemExit('Copied compile/archive inputs changed: '+','.join(changed))


def verify_artifact(path,expected):
    if sha(path)!=expected:raise SystemExit('Frozen standalone APK changed')


def self_test_provenance():
    checks=0
    def refused(action,label):
        nonlocal checks
        try:action()
        except(SystemExit,FileNotFoundError):checks+=1;return
        raise AssertionError('Mutation unexpectedly accepted: '+label)
    commit='a'*40
    def clean(*command):return commit if command==('rev-parse','HEAD')else''
    require_build_source(commit,clean);checks+=1
    refused(lambda:require_build_source(commit,lambda *command:'b'*40 if command==('rev-parse','HEAD')else''),'changed HEAD after snapshot')
    refused(lambda:require_build_source(commit,lambda *command:commit if command==('rev-parse','HEAD')else'changed.java'),'dirty tracked input after snapshot')
    temporary_parent=Path(__file__).resolve().parents[1]/'artifacts'
    temporary_parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bchat-c26-provenance-',dir=temporary_parent)as directory:
        base=Path(directory)
        names=(*INPUT_CONFIGS,'project/app/src/main/AndroidManifest.xml','project/app/src/main/java/Fixture.java',
               'project/app/src/main/res/values/strings.xml','frozen-inputs/tests/Harness.java','frozen-inputs/tools/tool.py')
        for name in names:
            path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('fixture:'+name).encode())
        expected=snapshot_records(base);verify_snapshot(base,expected);checks+=1
        # Live/worktree bytes are deliberately irrelevant to an already compiled immutable snapshot.
        live=base/'uncompiled-live.java';live.write_bytes(b'new HEAD source');verify_snapshot(base,expected);checks+=1
        for name in names:
            path=base/name;original=path.read_bytes();path.write_bytes(original+b'mutation')
            refused(lambda:verify_snapshot(base,expected),name);path.write_bytes(original)
        extra=base/'project/app/src/main/java/Unexpected.java';extra.write_bytes(b'extra')
        refused(lambda:verify_snapshot(base,expected),'extra compiled Java input');extra.unlink()
        missing=base/'frozen-inputs/tests/Harness.java';original=missing.read_bytes();missing.unlink()
        refused(lambda:verify_snapshot(base,expected),'missing archived harness');missing.write_bytes(original)
        artifact=base/'test.apk';artifact.write_bytes(b'fixture artifact');digest=sha(artifact);verify_artifact(artifact,digest);checks+=1
        artifact.write_bytes(b'changed artifact');refused(lambda:verify_artifact(artifact,digest),'changed APK')
        verify_snapshot(base,expected);checks+=1
    print('PASS',checks,'dry provenance checks; no product, Gradle, ADB, signing, or measurements')


parser=argparse.ArgumentParser()
parser.add_argument('--label')
parser.add_argument('--source-commit',help='Explicit accepted full40-character commit; build requires matching HEAD and clean tracked inputs')
parser.add_argument('--run-built',action='store_true',help='Only install/run the already built frozen test artifact, no concurrent build work')
parser.add_argument('--self-test-provenance',action='store_true',help='Dry mutation-rejection fixtures only; no product/build/native access')
args=parser.parse_args()
if args.self_test_provenance:self_test_provenance();raise SystemExit(0)
if not args.source_commit or not re.fullmatch(r'[0-9a-f]{40}',args.source_commit):raise SystemExit('Provide explicit full source commit')
EXPECTED=args.source_commit
if not args.label or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}',args.label):raise SystemExit('Unsafe evidence label')
root=Path(__file__).resolve().parents[1]
repo=root.parents[1]
tests=root/'tests/performance-android'
output=root/'artifacts/performance-android'/args.label
sdk=Path('D:/Codex/AndroidSdk')
gradle=Path('D:/Codex/tools/gradle-8.11.1/bin/gradle.bat')
signing=Path('C:/Users/hp/AppData/Local/Baseer/BChatSigning/fresh-install-20261009')


def run(*command,cwd=None,timeout=180):
    environment=os.environ.copy();environment['JAVA_HOME']='C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot'
    environment['ANDROID_HOME']=str(sdk)
    result=subprocess.run(list(map(str,command)),cwd=cwd,env=environment,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=timeout)
    with (output/'build-and-run.log').open('a',encoding='utf-8')as log:log.write(Path(str(command[0])).name+'\n'+result.stdout+result.stderr)
    if result.returncode:print((result.stdout+result.stderr)[-7000:]);raise SystemExit('Tool failed; preserved log, no performance acceptance')
    return result.stdout


def git(*command):return subprocess.check_output(['git','-C',str(repo),*command],text=True,encoding='utf-8').strip()
def committed(relative):return subprocess.check_output(['git','-C',str(repo),'show',EXPECTED+':'+relative])
if not args.run_built:
    require_build_source(EXPECTED,git)
    tracked=set(git('ls-tree','-r','--name-only',EXPECTED,'--','android/bchat/tests/performance-android','android/bchat/tools/test-performance-android.py').splitlines())
    required={source.relative_to(repo).as_posix()for source in tests.rglob('*')if source.is_file()}
    required.add(Path(__file__).resolve().relative_to(repo).as_posix())
    if required-tracked:raise SystemExit('Accepted source commit must track every harness/tool input before build: '+','.join(sorted(required-tracked)))
apk=output/'BChat-standalone-performance-tests.apk'
if not args.run_built:
    if output.exists():raise SystemExit('Do not overwrite prior evidence; use a fresh label')
    output.mkdir(parents=True)
    project=output/'project';(project/'app/src/main/java').mkdir(parents=True)
    inputs={};copied={};test_prefix='android/bchat/tests/performance-android/'
    def capture(relative,destination):
        data=committed(relative);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
        digest=hashlib.sha256(data).hexdigest();inputs[relative]=digest
        copied[destination.relative_to(output).as_posix()]=digest
        if sha(destination)!=digest:raise SystemExit('Commit blob differs from copied input: '+relative)
        return data
    for relative in sorted(tracked):capture(relative,output/'frozen-inputs'/relative)
    for name in ('build.gradle','settings.gradle','gradle.properties'):capture(test_prefix+name,project/name)
    app_template=capture(test_prefix+'app.gradle',output/'frozen-inputs'/test_prefix/'app.gradle')
    if app_template.count(BASELINE.encode())!=1:raise SystemExit('Expected exactly one explicit BuildConfig source-commit transformation')
    generated=app_template.replace(BASELINE.encode(),EXPECTED.encode())
    (project/'app/build.gradle').write_bytes(generated)
    copied['project/app/build.gradle']=hashlib.sha256(generated).hexdigest()
    capture(test_prefix+'AndroidManifest.xml',project/'app/src/main/AndroidManifest.xml')
    paths=git('ls-tree','-r','--name-only',EXPECTED,'--','android/bchat/app/src/main/java','android/bchat/app/src/main/res').splitlines()
    excluded=[]
    for relative in paths:
        source=repo/relative
        if source.name in ('BChatFirebaseMessagingService.java','BChatFirebaseTokenSource.java'):excluded.append(relative);continue
        destination=project/'app/src/main'/source.relative_to(root/'app/src/main')
        capture(relative,destination)
    for relative in sorted(tracked):
        if relative.startswith(test_prefix+'java/')and relative.endswith('.java'):
            capture(relative,project/'app/src/main/java'/relative.removeprefix(test_prefix+'java/'))
    require_build_source(EXPECTED,git);verify_snapshot(output,copied)
    manifest={'schema':3,'head':EXPECTED,'explicit_source_commit':args.source_commit,'source_sha256':inputs,
              'copied_input_sha256':copied,'snapshot_encoding':'exact canonical Git blob bytes from explicit commit; transformed app.gradle separately hashed',
              'excluded_tracked_sources':excluded,
              'baseline_reference':{'head':BASELINE,'manifest_sha256':'9cf4c4fc81e53f5a7693e20c7ffbf26c6188cb47955dfb2921d3d553603de653',
                  'results_sha256':'5296f8e2fbbbb187657bae424b242518959215d12631826113e45d895fb34a4e'},
              'production_delta_from_baseline':git('diff','--name-status',BASELINE,EXPECTED,'--','android/bchat/app/src/main/java','android/bchat/app/src/main/res').splitlines(),
              'harness_delta':['Room counters now real RecyclerView delegate create/bind/notify, not clickable LinearLayout child creation',
                  'Real admitRoomListSnapshot invoked only as explicit synthetic accepted-owner fixture, not authentication',
                  'Unchanged80ms/query plus bounded current-diff+layout wait included inside rooms-search; per-query wait recorded, never subtracted'],
              'excluded_all_untracked_product_sources':True,'scope':'Full production Activity exact-commit snapshot + test-only BuildConfig/manifest/harness, actual components/SQLite; no auth/HTTP/Firebase/network/media permissions, not product release/performance acceptance'}
    (output/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    require_build_source(EXPECTED,git);verify_snapshot(output,copied)
    try:run(gradle,':app:assembleDebug','--offline','--no-daemon','--console=plain',cwd=project,timeout=240)
    finally:require_build_source(EXPECTED,git);verify_snapshot(output,copied)
    unsigned=list((project/'app/build/outputs/apk/debug').glob('*-unsigned.apk'))
    if len(unsigned)!=1:raise SystemExit('Expected exactly one unsigned standalone artifact, no debug-key fallback')
    run(sdk/'build-tools/35.0.0/apksigner.bat','sign','--ks',signing/'bchat-preview-fresh.p12','--ks-key-alias','bchat-preview',
        '--ks-pass','file:'+str(signing/'keystore.password'),'--out',apk,unsigned[0])
    run(sdk/'build-tools/35.0.0/apksigner.bat','verify',apk)
    require_build_source(EXPECTED,git);verify_snapshot(output,copied)
    manifest['test_apk_sha256']=sha(apk)
    (output/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Standalone full-Activity test build complete. Request exclusive host/emulator window before --run-built.',flush=True)
manifest=json.loads((output/'source-manifest.json').read_text(encoding='utf-8'))
manifest_digest=sha(output/'source-manifest.json')
if manifest['head']!=EXPECTED:raise SystemExit('Requested source commit differs from compiled snapshot')
archived_tool=output/'frozen-inputs'/Path(__file__).resolve().relative_to(repo)
if Path(__file__).read_bytes().replace(b'\r\n',b'\n')!=archived_tool.read_bytes().replace(b'\r\n',b'\n'):
    raise SystemExit('Executing tool differs from the frozen commit tool (only Git CRLF conversion is normalized)')


def frozen():
    if sha(output/'source-manifest.json')!=manifest_digest:raise SystemExit('Compiled snapshot manifest changed during invocation')
    verify_snapshot(output,manifest['copied_input_sha256'])
    verify_artifact(apk,manifest['test_apk_sha256'])


frozen()
if args.run_built:
    provenance={'compiled_snapshot_head':manifest['head'],'head_at_run_start':git('rev-parse','HEAD'),
                'explicit_source_commit':args.source_commit,'compiled_inputs_verified_by_manifest':True,'later_uncompiled_product_sources_excluded':True,
                'compiled_manifest_sha256':manifest_digest,'acceptance_gate':'frozen copied project/archive/APK; current HEAD is provenance only for run-built',
                'harness_delta':manifest['harness_delta'],'baseline_reference':manifest['baseline_reference']}
    (output/'run-provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    adb=sdk/'platform-tools/adb.exe'
    run(adb,'-s','emulator-5580','install','-r',apk)
    frozen()
    try:result=run(adb,'-s','emulator-5580','shell','am','instrument','-w','-r',PACKAGE+'/com.baseer.freshchat.PerformanceInstrumentation',timeout=180)
    finally:frozen()
    (output/'instrumentation.log').write_text(result,encoding='utf-8')
    native=subprocess.run([str(adb),'-s','emulator-5580','exec-out','run-as',PACKAGE,'cat','files/performance-results.json'],capture_output=True,timeout=20)
    if native.returncode:raise SystemExit('No actual native result; no numbers manufactured')
    (output/'performance-results.json').write_bytes(native.stdout)
    evidence=json.loads(native.stdout);print(result,flush=True);frozen()
    provenance['head_at_run_end']=git('rev-parse','HEAD')
    (output/'run-provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    if not evidence.get('passed')or'INSTRUMENTATION_CODE: -1'not in result:raise SystemExit('Harness/scenario failure; raw/partial evidence retained, no baseline accepted')
    if evidence.get('blocked_input_visibility_observations'):print('PARTIAL collection: input visibility BLOCKED/null; no input-latency acceptance')
    print('Full Activity fixture measurements retained for independent baseline review only; no product-performance claim')
