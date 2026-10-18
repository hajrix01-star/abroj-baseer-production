#!/usr/bin/env python3
"""Build isolated Android35 transfer acceptance. Platform services are real; HTTP is a named fake.
No dependency download, production APK, installation or external endpoint is performed here.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import zipfile
import argparse

parser=argparse.ArgumentParser()
parser.add_argument('--draft-only',action='store_true')
parser.add_argument('--death-only',action='store_true')
parser.add_argument('--guards-only',action='store_true')
parser.add_argument('--stage-only',action='store_true')
parser.add_argument('--before-stage-fix',action='store_true',help='Negative control: historical missing fence/import-before-drain ordering in temporary helper only')
parser.add_argument('--before-guards-fix',action='store_true',help='Negative control: exact historical missing scope/receipt/quota guards in temporary test sources only')
parser.add_argument('--before-draft-fix',action='store_true',help='Negative control: restore the exact pre-fix raw-only draft predicate in a temporary test source')
args_cli=parser.parse_args()
if args_cli.before_draft_fix and not args_cli.draft_only:parser.error('--before-draft-fix requires --draft-only')
if args_cli.death_only and args_cli.draft_only:parser.error('Choose one focused instrumentation')
if args_cli.before_guards_fix and not args_cli.guards_only:parser.error('--before-guards-fix requires --guards-only')
if args_cli.before_stage_fix and not args_cli.stage_only:parser.error('--before-stage-fix requires --stage-only')

root=Path(__file__).resolve().parents[1]
sdk=Path(os.environ.get('ANDROID_HOME','D:/Codex/AndroidSdk'))
tools=sdk/'build-tools/35.0.0'
android=sdk/'platforms/android-35/android.jar'
suffix='.exe' if os.name=='nt' else ''
folder_root=root/'artifacts/test-runtime'
folder_root.mkdir(parents=True,exist_ok=True)
name='BChat-Draft-Tests' if args_cli.draft_only else 'BChat-Transfer-Tests'
if args_cli.death_only:name='BChat-Transfer-Death-Tests'
if args_cli.guards_only:name='BChat-Transfer-Guard-Tests'
if args_cli.stage_only:name='BChat-Stage-Tests'
if args_cli.before_draft_fix:name+='-BEFORE-FIX'
if args_cli.before_guards_fix:name+='-BEFORE-FIX'
if args_cli.before_stage_fix:name+='-BEFORE-FIX'
output=root/('artifacts/'+name+'-UNSIGNED.apk')
with tempfile.TemporaryDirectory(prefix='transfer-tests-',dir=folder_root) as temp:
    folder=Path(temp)
    classes,dex,resources,java=[folder/name for name in ['classes','dex','resources','java']]
    for directory in [classes,dex,resources,java]:directory.mkdir()
    values=resources/'values';values.mkdir()
    # Exact production transfer strings only; no parallel product resources are authored.
    import xml.etree.ElementTree as ET
    source=ET.parse(root/'app/src/main/res/values-en/strings.xml').getroot()
    strings=ET.Element('resources')
    for value in source.findall('string'):
        if value.attrib['name'].startswith('bchat_transfer_'):strings.append(value)
    ET.ElementTree(strings).write(values/'strings.xml',encoding='utf-8',xml_declaration=True)
    archive=folder/'resources.zip'
    subprocess.run([str(tools/('aapt2'+suffix)),'compile','--dir',str(resources),'-o',str(archive)],check=True)
    base=folder/'base.apk'
    manifest=root/'tests/transfers-android/AndroidManifest.xml'
    if args_cli.draft_only or args_cli.death_only or args_cli.guards_only or args_cli.stage_only:
        manifest=folder/'AndroidManifest.xml'
        manifest.write_text((root/'tests/transfers-android/AndroidManifest.xml').read_text(encoding='utf-8')
                            .replace('TransferInstrumentation','DraftRevisionInstrumentation' if args_cli.draft_only
                                     else 'TransferAdmissionInstrumentation' if args_cli.guards_only
                                     else 'StageAdmissionInstrumentation' if args_cli.stage_only else 'TransferProcessDeathInstrumentation'),encoding='utf-8')
    subprocess.run([str(tools/('aapt2'+suffix)),'link','-o',str(base),'-I',str(android),'--manifest',
                    str(manifest),'--java',str(java),
                    '--custom-package','com.baseer.freshchat',str(archive)],check=True)
    product=root/'app/src/main/java/com/baseer/freshchat'
    sources=list((product/'sync').glob('*.java'))
    if args_cli.before_stage_fix:
        original=product/'sync/BChatStageAdmission.java';source_text=original.read_text(encoding='utf-8')
        start=source_text.index('        for(BChatSendTickets.Ticket ticket:box.tickets().forAccount(a)){')
        end=source_text.index('        boolean staging=active(a,room,member),blocked=staging;',start)
        drain=source_text[start:end]
        source_text=source_text[:start]+source_text[end:]
        source_text=source_text.replace('boolean staging=active(a,room,member),blocked=staging;','boolean staging=false,blocked=false;')
        source_text=source_text.replace('        Map<String,Long> sequence=new HashMap<>();',drain+'        Map<String,Long> sequence=new HashMap<>();')
        frozen=folder/'BChatStageAdmission.java';frozen.write_text(source_text,encoding='utf-8')
        sources=[path for path in sources if path!=original]+[frozen]
    if args_cli.before_draft_fix:
        original=product/'sync/BChatV2Outbox.java'
        weakened=original.read_text(encoding='utf-8')
        assert weakened.count(' AND editor_revision=CAST(? AS INTEGER)')==1
        weakened=weakened.replace(' AND editor_revision=CAST(? AS INTEGER)','').replace(',""+reply,""+revision}',',""+reply}')
        frozen=folder/'BChatV2Outbox.java';frozen.write_text(weakened,encoding='utf-8')
        sources=[path for path in sources if path!=original]+[frozen]
    sources += [product/(name+'.java') for name in ['BChatTransferCoordinator','BChatTransferJobService','BChatTransferService']]
    if args_cli.before_guards_fix:
        for relative,old,new in [
            ('BChatTransferCoordinator.java',
             'if(scope==null||ticket==null||entry==null||!scope.key.equals(entry.accountKey)\n                ||!"media".equals(ticket.kind)||!"sending".equals(ticket.state)||!ticket.matches(entry))return false;',
             '// Negative control: historical scope guard absent.'),
            ('sync/BChatV2Outbox.java','if(requireReceipt){','if(false&&requireReceipt){'),
            ('sync/BChatSendTickets.java','if(count.getLong(0)>=BChatConnectedMediaStore.MAX_PENDING_REQUESTS)',
             'if(false&&count.getLong(0)>=BChatConnectedMediaStore.MAX_PENDING_REQUESTS)')]:
            original=product/relative;text=original.read_text(encoding='utf-8');assert text.count(old)==1,relative
            frozen=folder/original.name;frozen.write_text(text.replace(old,new),encoding='utf-8')
            sources=[path for path in sources if path!=original]+[frozen]
    sources += list((root/'tests/transfers-android').rglob('*.java'))+list(java.rglob('*.java'))
    service=(product/'BChatTransferService.java').read_text(encoding='utf-8')
    service_body=service[service.index('{')+1:service.rindex('}')]
    probe=folder/'TransferFallbackProbe.java'
    probe.write_text((root/'tests/transfers-android/TransferFallbackProbe.java.in').read_text(encoding='utf-8')
                     .replace('%PRODUCTION_BODY%',service_body),encoding='utf-8')
    sources.append(probe)
    subprocess.run([shutil.which('javac'),'-encoding','UTF-8','-source','8','-target','8','-Xlint:-options',
                    '-cp',str(android),'-d',str(classes),*map(str,sources)],check=True)
    args=folder/'classes.txt'
    args.write_text('\n'.join(str(file).replace('\\','/') for file in classes.rglob('*.class')),encoding='utf-8')
    subprocess.run([str(tools/('d8.bat' if os.name=='nt' else 'd8')),'--min-api','26','--lib',str(android),
                    '--output',str(dex),'@'+str(args)],check=True)
    with zipfile.ZipFile(base,'a',compression=zipfile.ZIP_DEFLATED) as apk:
        for file in dex.glob('classes*.dex'):apk.write(file,file.name)
    subprocess.run([str(tools/('zipalign'+suffix)),'-f','4',str(base),str(output)],check=True)
print(output)
print('Unsigned isolated transfer test APK; product unchanged; execution not claimed.')
