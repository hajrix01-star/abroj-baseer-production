#!/usr/bin/env python3
"""Source tripwires only; no native payload or security probes."""
from pathlib import Path
import xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1];src=root/'app/src/main/java/com/baseer/bwork/legacy'
a=(src/'AttachmentSupport.java').read_text();v=(src/'ImagePreviewView.java').read_text();i=(src/'ImagePreviews.java').read_text();p=(src/'PdfPreviewView.java').read_text();audio=(src/'AudioPlayback.java').read_text();n=0
def check(value,label):
 global n
 assert value,label
 n+=1
 print('PASS '+label)
def body(text,signature):
 start=text.index('{',text.index(signature));depth=1
 for j in range(start+1,len(text)):
  if text[j]=='{':depth+=1
  elif text[j]=='}':depth-=1
  if depth==0:return text[start+1:j]
 raise AssertionError(signature)
check('validateImportedSize(declaredSize, size, mime)' in a,'Provider byte completeness checked before admission')
check('new DigestInputStream(original, digest)' in a and 'hex(digest.digest())' in a,'Import fingerprints original byte stream')
check('withIntegrity(Context context' in a,'New camera/voice has explicit worker-side admission helper')
export=body(a,'public static void saveToUri(')
check(export.index('verifyDigest(source, attachment.sha256)')<export.index('openOutputStream'),'Digest validated before destination opens')
check('ATTACHMENT_EXPORT_PARTIAL' in export,'Export warning distinguishes incomplete destination')
check('expected != null' in a,'Legacy null digest remains supported')
check('BitmapRegionDecoder.newInstance' in i and 'MAX_BITMAP_BYTES' in i,'Detail decoding has allocation bounds')
check('detailPending.size() >= MAX_PENDING' in i and 'job.cancelled' in i,'Detail queue and cancellation bounded')
check('ScaleGestureDetector' in v and 'onDoubleTap' in v and 'onScroll' in v,'Inspector exposes zoom and pan')
check('media_zoom_fit' in v and 'media_zoom_in' in v and 'media_zoom_out' in v,'Inspector exposes named controls')
request=body(v,'private void requestTile()');attempt=body(v,'private void requestTileAttempt(');draw=body(v,'protected void onDraw(Canvas')
check('setDeadline(token)' in request and 'setDeadline' not in attempt,'One deadline per viewport')
check(attempt.index('if (result.busy)')<attempt.index('clearDeadline()'),'Busy retry preserves original deadline')
check('region.equals(requestedRegion) && sample == requestedSample' in request,'Same-viewport redraw cannot renew budget')
check('removeCallbacks(tileRetry)' in body(v,'private void setDeadline('),'Timeout removes retries')
check('new ' not in draw and 'orientationMatrix()' not in draw,'Drawing reuses geometry')
check('WORKER.submit' in p and 'Looper.myLooper() == Looper.getMainLooper()' in p,'PDF render is off-main')
check('new ArrayBlockingQueue<>(4)' in p and 'token != generation' in p,'PDF queue and late results fenced')
check('clearDisplay()' in p and 'onWindowVisibilityChanged' in p,'Hidden PDF releases display ownership')
check('ACTION_AUDIO_BECOMING_NOISY' in audio and 'unregisterReceiver(noisyReceiver)' in audio,'Route-loss pause has bounded receiver lifecycle')
check('setReadable' not in a+audio and 'MODE_WORLD' not in a+audio,'No broad file permission introduced')
catalogs=[{s.attrib['name'] for s in ET.parse(root/'app/src/main/res'/loc/'media_foundations.xml').getroot()} for loc in ['values','values-ar','values-en']]
check(catalogs[0]==catalogs[1]==catalogs[2],'Media locale keys match')
print(f'PASS {n} recovered source checks; Android NOT executed')
