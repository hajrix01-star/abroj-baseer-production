#!/usr/bin/env python3
"""C11 actual projection JVM + isolated AndroidX/full-Activity functional fixture; never benchmark."""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, subprocess, xml.etree.ElementTree as XML

parser=argparse.ArgumentParser()
parser.add_argument('--build-android',action='store_true')
parser.add_argument('--run-built',action='store_true')
parser.add_argument('--label',default='jvm')
parser.add_argument('--ui-dark-font2',action='store_true')
parser.add_argument('--preflight-only',action='store_true')
args=parser.parse_args()
if not args.label.replace('-','').isalnum():raise SystemExit('Unsafe label')
root=Path(__file__).resolve().parents[1];repo=root.parents[1]
tests=root/'tests/room-list';out=root/'artifacts/room-list'/args.label
native_java=Path('C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot')
sdk=Path('D:/Codex/AndroidSdk');package='com.baseer.bchat.room.list.test'
def jvm_tool(name):
    configured=os.environ.get('JAVA_HOME')
    if configured:
        candidate=Path(configured)/'bin'/(name+'.exe'if os.name=='nt'else name)
        if candidate.is_file():return candidate
    found=shutil.which(name)
    if not found:raise SystemExit('Set JAVA_HOME or PATH to an installed JDK providing '+name)
    return Path(found)
def preflight():
    android='{http://schemas.android.com/apk/res/android}'
    product=XML.parse(root/'app/src/main/AndroidManifest.xml').getroot()
    fixture=XML.parse(tests/'AndroidManifest.xml').getroot()
    if product.find('application').get(android+'supportsRtl')!=fixture.find('application').get(android+'supportsRtl')or fixture.find('application').get(android+'supportsRtl')!='true':raise SystemExit('supportsRtl preflight mismatch')
    if fixture.findall('uses-permission'):raise SystemExit('Fixture must have no network/media permissions')
    production=(root/'app/build.gradle').read_text();fixture_gradle=(out/'project/app/build.gradle')if args.run_built else(root/'tests/performance-android/app.gradle')
    compiled=fixture_gradle.read_text()
    for field,expected in [('minSdk','26'),('targetSdk','35')]:
        if re.search(field+r'\s+(\d+)',production).group(1)!=re.search(field+r'\s+(\d+)',compiled).group(1)or re.search(field+r'\s+(\d+)',compiled).group(1)!=expected:raise SystemExit('SDK preflight mismatch '+field)
    print('PRE-FLIGHT PASS product/fixture supportsRtl:true,min26,target35,noINTERNET',flush=True)
if args.build_android or args.run_built or args.preflight_only:preflight()
if args.preflight_only:raise SystemExit(0)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run(*command,cwd=None,timeout=180):
    env=os.environ.copy()
    if args.build_android or args.run_built:env['JAVA_HOME']=str(native_java);env['ANDROID_HOME']=str(sdk)
    result=subprocess.run(list(map(str,command)),cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    with (out/'raw.log').open('a',encoding='utf-8')as log:log.write(Path(str(command[0])).name+'\n'+result.stdout+result.stderr)
    if result.returncode:print(result.stdout+result.stderr);raise SystemExit('Failed; raw evidence retained')
    return result.stdout
if not args.run_built:
    if out.exists():raise SystemExit('Preserve old evidence; choose fresh label')
    out.mkdir(parents=True)
    if not args.build_android:
        classes=out/'classes';classes.mkdir()
        source=root/'app/src/main/java/com/baseer/freshchat/BChatRoomRow.java'
        run(jvm_tool('javac'),'-encoding','UTF-8','-d',classes,source,tests/'RoomRowTest.java')
        print(run(jvm_tool('java'),'-cp',classes,'com.baseer.freshchat.RoomRowTest'))
        (out/'source-manifest.json').write_text(json.dumps({str(source.relative_to(repo)):sha(source),str((tests/'RoomRowTest.java').relative_to(repo)):sha(tests/'RoomRowTest.java')},indent=2),encoding='utf-8')
        raise SystemExit(0)
    project=out/'project';(project/'app/src/main/java').mkdir(parents=True)
    template=root/'tests/performance-android'
    for name in ('build.gradle','settings.gradle','gradle.properties'):shutil.copyfile(template/name,project/name)
    (project/'app/build.gradle').write_text((template/'app.gradle').read_text().replace('com.baseer.bchat.performance.test',package)
        .replace('C26-isolated-baseline','C11-isolated-functional').replace('2570f3af16ba682c722039b29cf65376490a7c57','C11-functional-working-tree'),encoding='utf-8')
    shutil.copyfile(tests/'AndroidManifest.xml',project/'app/src/main/AndroidManifest.xml')
    tracked=subprocess.check_output(['git','-C',str(repo),'ls-files','--','android/bchat/app/src/main/java','android/bchat/app/src/main/res'],text=True).splitlines()
    # Exact owned new product files only, not unrelated unfinished/untracked components.
    tracked+=['android/bchat/app/src/main/java/com/baseer/freshchat/'+name for name in ('BChatRoomRow.java','BChatRoomListAdapter.java','BChatCartSheet.java','OrderQuantityStepper.java')]
    sources={}
    for relative in sorted(set(tracked)):
        source=repo/relative
        if source.name in ('BChatFirebaseMessagingService.java','BChatFirebaseTokenSource.java'):continue
        target=project/'app/src/main'/source.relative_to(root/'app/src/main');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        sources[relative]=sha(source)
    for source in tests.rglob('*'):
        if source.is_file():sources[source.relative_to(repo).as_posix()]=sha(source)
    for source in (template/'app.gradle',template/'build.gradle',template/'settings.gradle',template/'gradle.properties',Path(__file__).resolve()):sources[source.relative_to(repo).as_posix()]=sha(source)
    for relative in sources:
        if relative.startswith('android/bchat/tests/')or relative=='android/bchat/tools/test-room-list.py':
            destination=out/'frozen-inputs'/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/relative,destination)
    for source in (tests/'java').rglob('*.java'):
        target=project/'app/src/main/java'/source.relative_to(tests/'java');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    manifest={'source_sha256':sources,'head_at_snapshot':subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),
        'working_tree_bytes_not_commit_identity':True,'compile_only_dependencies':['BChatCartSheet.java','OrderQuantityStepper.java'],
        'scope':'Android35 full Activity synthetic identity/list/avatars; real AndroidX differ/views. NOT auth/HTTP/benchmark/cart acceptance/product release.'}
    (out/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    run('D:/Codex/tools/gradle-8.11.1/bin/gradle.bat',':app:assembleDebug','--offline','--no-daemon','--console=plain',cwd=project,timeout=240)
    unsigned=list((project/'app/build/outputs/apk/debug').glob('*-unsigned.apk'))
    if len(unsigned)!=1:raise SystemExit('No unsigned isolated artifact')
    signing=Path('C:/Users/hp/AppData/Local/Baseer/BChatSigning/fresh-install-20261009')
    run(sdk/'build-tools/35.0.0/apksigner.bat','sign','--ks',signing/'bchat-preview-fresh.p12','--ks-key-alias','bchat-preview','--ks-pass','file:'+str(signing/'keystore.password'),'--out',out/'room-list-tests.apk',unsigned[0])
    manifest['test_apk_sha256']=sha(out/'room-list-tests.apk')
    (out/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Built isolated functional test only. Coordinate emulator lease before --run-built.')
if args.run_built:
    manifest=json.loads((out/'source-manifest.json').read_text());changes=[path for path,value in manifest['source_sha256'].items()if sha(repo/path)!=value]
    if changes:raise SystemExit('Sources changed before isolated run: '+','.join(changes))
    if sha(out/'room-list-tests.apk')!=manifest['test_apk_sha256']:raise SystemExit('Test artifact changed')
    run(sdk/'platform-tools/adb.exe','-s','emulator-5580','install','-r',out/'room-list-tests.apk')
    native_args=['-e','componentOnly','darkFont2']if args.ui_dark_font2 else[]
    result=run(sdk/'platform-tools/adb.exe','-s','emulator-5580','shell','am','instrument','-w','-r',*native_args,package+'/com.baseer.freshchat.RoomListInstrumentation')
    print(result)
    native=subprocess.run([str(sdk/'platform-tools/adb.exe'),'-s','emulator-5580','exec-out','run-as',package,'cat','files/room-list-results.json'],capture_output=True,timeout=20)
    if native.returncode==0:(out/'room-list-results.json').write_bytes(native.stdout)
    for locale in ('ar','en'):
        for theme in ('light','dark'):
            for scale in ('1','2'):
                name='rooms-'+locale+'-'+theme+'-font'+scale+'.png'
                capture=subprocess.run([str(sdk/'platform-tools/adb.exe'),'-s','emulator-5580','exec-out','run-as',package,'cat','files/'+name],capture_output=True,timeout=20)
                if capture.returncode==0:(out/name).write_bytes(capture.stdout)
    if 'INSTRUMENTATION_CODE: -1'not in result or 'PASS 'not in result:raise SystemExit('Native failed')
    changes=[path for path,value in manifest['source_sha256'].items()if sha(repo/path)!=value]
    if changes:raise SystemExit('Sources changed during run; reject provenance: '+','.join(changes))
