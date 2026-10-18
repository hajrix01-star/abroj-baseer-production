#!/usr/bin/env python3
"""Compile/test only the two pure timeline components; no Activity/native/performance/dependency work."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('--label',default='jvm-initial')
args=parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',args.label):raise SystemExit('Unsafe evidence label')
root=Path(__file__).resolve().parents[1];repo=root.parents[1]
out=root/'artifacts/timeline-rows'/args.label
if out.exists():raise SystemExit('Preserve prior evidence; use a fresh label')
out.mkdir(parents=True);classes=out/'classes';classes.mkdir()
files=[root/'app/src/main/java/com/baseer/freshchat'/name for name in ('BChatTimelineRows.java','BChatTimelineChangePlan.java')]
files.append(root/'tests/timeline-rows/TimelineRowsTest.java');files.append(Path(__file__).resolve())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
inputs={path.relative_to(repo).as_posix():sha(path)for path in files}
copies={}
for path in files:
    relative=path.relative_to(repo);target=out/'frozen-inputs'/relative
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target);copies[relative.as_posix()]=sha(target)
if inputs!=copies:raise SystemExit('Input changed while copying fixture')
def jdk(name):
    configured=os.environ.get('JAVA_HOME')
    if configured:
        path=Path(configured)/'bin'/(name+'.exe'if os.name=='nt'else name)
        if path.is_file():return path
    path=shutil.which(name)
    if not path:raise SystemExit('Set JAVA_HOME/PATH to an installed JDK17')
    return Path(path)
def frozen():
    if any(sha(repo/path)!=digest or sha(out/'frozen-inputs'/path)!=digest for path,digest in inputs.items()):
        raise SystemExit('Live/frozen inputs changed; no test acceptance')
def run(*command):
    result=subprocess.run(list(map(str,command)),text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=60)
    with (out/'raw.log').open('a',encoding='utf-8')as log:log.write(Path(str(command[0])).name+'\n'+result.stdout+result.stderr)
    if result.returncode:print(result.stdout+result.stderr);raise SystemExit('Pure component test failed; raw retained')
    return result.stdout
manifest={'source_sha256':inputs,'copied_sha256':copies,'scope':'Two pure production classes + exact test, Java8 target/JDK17. No Activity/Android/SQLite/auth/wire/benchmark acceptance.'}
(out/'source-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
frozen()
run(jdk('javac'),'--release','8','-encoding','UTF-8','-d',classes,*[out/'frozen-inputs'/path.relative_to(repo)for path in files if path.suffix=='.java'])
frozen();result=run(jdk('java'),'-cp',classes,'com.baseer.freshchat.TimelineRowsTest');frozen();print(result,end='')
matched=re.fullmatch(r'PASS (\d+) pure timeline row/plan checks;.*\s*',result)
if not matched:raise SystemExit('No actual check count; no acceptance fabricated')
(out/'result.json').write_text(json.dumps({'passed':True,'checks':int(matched.group(1)),'stdout':result},indent=2),encoding='utf-8')
