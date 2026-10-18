#!/usr/bin/env python3
"""C16 native component only. Frozen real Panel/Protocol/Ui, synthetic Host, actual AndroidX/SDK JSON."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import xml.etree.ElementTree as XML

BASE='b8aa47a936a4ed99121990bc61708181714cea12'
PACKAGE='com.baseer.bchat.room.explore.test'
TARGETS={'BChatRoomExplorePanel.java':'56e9b3d2f8ed070233adb1f286b6d7375bf7aa67213d3928a644731566154cf5',
         'RoomExploreProtocol.java':'5bb727fc19fb7d5d891960cd9f3e02f9034e30884b0f9a91527053c9143afab8'}
parser=argparse.ArgumentParser()
parser.add_argument('--label',required=True)
parser.add_argument('--run-built',action='store_true')
args=parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}',args.label):raise SystemExit('Unsafe evidence label')
root=Path(__file__).resolve().parents[1];repo=root.parents[1];tests=root/'tests/room-explore-android'
out=root/'artifacts/room-explore-android'/args.label;project=out/'project';apk=out/'BChat-standalone-room-explore-tests.apk'
sdk=Path('D:/Codex/AndroidSdk');gradle=Path('D:/Codex/tools/gradle-8.11.1/bin/gradle.bat')
signing=Path('C:/Users/hp/AppData/Local/Baseer/BChatSigning/fresh-install-20261009')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def blob(relative):return subprocess.check_output(['git','-C',str(repo),'show',BASE+':'+relative])
def head():return subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
def run(*command,cwd=None,timeout=180):
    env=os.environ.copy();env['JAVA_HOME']='C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot';env['ANDROID_HOME']=str(sdk)
    result=subprocess.run(list(map(str,command)),cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    with (out/'build-and-run.log').open('a',encoding='utf-8')as log:log.write(Path(str(command[0])).name+'\n'+result.stdout+result.stderr)
    if result.returncode:print((result.stdout+result.stderr)[-8000:]);raise SystemExit('Native component tool failed; raw preserved')
    return result.stdout
def copied_records():
    files=[project/name for name in ('build.gradle','settings.gradle','gradle.properties','app/build.gradle')]
    files.extend(p for base in (project/'app/src',out/'frozen-inputs')for p in base.rglob('*')if p.is_file())
    return {p.relative_to(out).as_posix():sha(p)for p in files}
if not args.run_built:
    if out.exists():raise SystemExit('Preserve prior evidence; choose new label')
    out.mkdir(parents=True);(project/'app/src/main/java').mkdir(parents=True)
    captured={};sources={};epochs={}
    def capture(relative,destination,data,epoch):
        digest=hashlib.sha256(data).hexdigest();destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
        captured[destination.relative_to(out).as_posix()]=digest;sources[relative]=digest;epochs[relative]=epoch
        if sha(destination)!=digest:raise SystemExit('Snapshot copy mismatch')
    def git_source(relative,destination):capture(relative,destination,blob(relative),'Git '+BASE)
    for name in ('build.gradle','settings.gradle','gradle.properties'):
        git_source('android/bchat/tests/performance-android/'+name,project/name)
    prefix='android/bchat/app/src/main/java/com/baseer/freshchat/'
    names=('Ui','UiPalette','ChatAppearance','AvatarInitials','AppLocale','AppLocalePolicy','LocalSettings','LocalSettingsPolicy','ReplyWireContract')
    for name in [name+'.java'for name in names]+['sync/AccountScope.java','sync/OutboxPolicy.java','sync/BChatConnectedMediaStore.java']:
        git_source(prefix+name,project/'app/src/main/java/com/baseer/freshchat'/name)
    for name,expected in TARGETS.items():
        source=repo/prefix/name
        if sha(source)!=expected:raise SystemExit('Frozen target changed before build: '+name)
        capture(prefix+name,project/'app/src/main/java/com/baseer/freshchat'/name,source.read_bytes(),'actual live target reviewed '+expected)
    for source in (root/'app/src/main/res').rglob('*'):
        if source.is_file():capture(source.relative_to(repo).as_posix(),project/'app/src/main/res'/source.relative_to(root/'app/src/main/res'),source.read_bytes(),'actual live resources at snapshot')
    for source in tests.rglob('*'):
        if not source.is_file():continue
        relative=source.relative_to(repo).as_posix();data=source.read_bytes()
        capture(relative,out/'frozen-inputs'/relative,data,'test fixture')
        if source.name=='app.gradle':capture(relative,project/'app/build.gradle',data,'test fixture')
        elif source.name=='AndroidManifest.xml':capture(relative,project/'app/src/main/AndroidManifest.xml',data,'test fixture')
        elif source.suffix=='.java':capture(relative,project/'app/src/main/java'/source.relative_to(tests/'java'),data,'test fixture')
    cases=root/'tests/room-explore/com/baseer/freshchat/RoomExploreCases.java'
    capture(cases.relative_to(repo).as_posix(),project/'app/src/main/java/com/baseer/freshchat/RoomExploreCases.java',cases.read_bytes(),'actual shared91 cases, no adapter sources')
    own=Path(__file__).resolve();capture(own.relative_to(repo).as_posix(),out/'frozen-inputs'/own.relative_to(repo),own.read_bytes(),'executing tool')
    # Manifest isolation/preflight is the same platform contract as product, no network/media permissions.
    android='{http://schemas.android.com/apk/res/android}';fixture=XML.parse(project/'app/src/main/AndroidManifest.xml').getroot()
    product=XML.fromstring(blob('android/bchat/app/src/main/AndroidManifest.xml'))
    if fixture.findall('uses-permission')or fixture.find('application').get(android+'supportsRtl')!='true' or product.find('application').get(android+'supportsRtl')!='true':raise SystemExit('Native isolation/RTL preflight failed')
    fixture_gradle=(project/'app/build.gradle').read_text();product_gradle=blob('android/bchat/app/build.gradle').decode()
    for key,expected in [('minSdk','26'),('targetSdk','35')]:
        if re.search(key+r'\s+(\d+)',fixture_gradle).group(1)!=expected or re.search(key+r'\s+(\d+)',product_gradle).group(1)!=expected:raise SystemExit('SDK preflight failed')
    manifest={'schema':1,'head_at_snapshot':head(),'base_compile_epoch':BASE,'source_sha256':sources,'source_epoch':epochs,'copied_input_sha256':captured,
        'scope':'Actual target Panel/Protocol + baseGit Ui/helpers/actual media constant owner; actual resources/AndroidX/native JSON. Synthetic Host HTTP/auth/formatter. No OdooIdentityActivity/Controller/Index/Port/JSON adapter/constant shim/network/media/receipt/performance claim.'}
    if copied_records()!=captured:raise SystemExit('Unexpected/mutated copied source before build')
    (out/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    run(gradle,':app:assembleDebug','--offline','--no-daemon','--console=plain',cwd=project,timeout=240)
    if copied_records()!=captured:raise SystemExit('Copied inputs changed during build')
    unsigned=list((project/'app/build/outputs/apk/debug').glob('*-unsigned.apk'))
    if len(unsigned)!=1:raise SystemExit('Expected one unsigned standalone APK, no debug signer fallback')
    run(sdk/'build-tools/35.0.0/apksigner.bat','sign','--ks',signing/'bchat-preview-fresh.p12','--ks-key-alias','bchat-preview','--ks-pass','file:'+str(signing/'keystore.password'),'--out',apk,unsigned[0])
    run(sdk/'build-tools/35.0.0/apksigner.bat','verify',apk);manifest['test_apk_sha256']=sha(apk)
    (out/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Built isolated room-explore test APK; no product APK. Use reserved emulator only for --run-built.')
manifest=json.loads((out/'source-manifest.json').read_text());digest=sha(out/'source-manifest.json')
def frozen():
    if sha(out/'source-manifest.json')!=digest or copied_records()!=manifest['copied_input_sha256']or sha(apk)!=manifest['test_apk_sha256']:raise SystemExit('Frozen copies/manifest/APK changed; no acceptance')
frozen()
if args.run_built:
    provenance={'head_at_run_start':head(),'compiled_epochs':manifest['source_epoch'],'manifest_sha256':digest,'scope':manifest['scope']}
    (out/'run-provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    adb=sdk/'platform-tools/adb.exe';run(adb,'-s','emulator-5580','install','-r',apk)
    frozen()
    try:result=run(adb,'-s','emulator-5580','shell','am','instrument','-w','-r',PACKAGE+'/com.baseer.freshchat.ExploreInstrumentation',timeout=240)
    finally:frozen()
    (out/'instrumentation.log').write_text(result,encoding='utf-8')
    def collect(name):
        captured=subprocess.run([str(adb),'-s','emulator-5580','exec-out','run-as',PACKAGE,'cat','files/'+name],capture_output=True,timeout=15)
        if captured.returncode:return None
        return captured.stdout
    data=collect('room-explore-results.json')
    if not data:raise SystemExit('No actual native result')
    (out/'room-explore-results.json').write_bytes(data);evidence=json.loads(data);(out/'captures').mkdir(exist_ok=True)
    for name in evidence.get('captures',[]):
        if not re.fullmatch(r'explore-[a-z0-9-]+\.png',name):raise SystemExit('Unsafe capture filename')
        capture=collect(name)
        if not capture or not capture.startswith(b'\x89PNG\r\n\x1a\n'):raise SystemExit('Missing real capture: '+name)
        (out/'captures'/name).write_bytes(capture)
    frozen();provenance['head_at_run_end']=head();(out/'run-provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8');print(result)
    if not evidence.get('passed')or'INSTRUMENTATION_CODE: -1'not in result:raise SystemExit('Fixture/product finding preserved; stop before any product edit or rerun')
    if len(evidence.get('renders',[]))!=8 or evidence.get('protocol_checks')!=91:raise SystemExit('Incomplete native configurations/protocol evidence')
    print('PASS actual component scope only; no HTTP/auth/media/receipt/Activity/performance acceptance')
