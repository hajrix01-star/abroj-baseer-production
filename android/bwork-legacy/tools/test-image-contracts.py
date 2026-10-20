#!/usr/bin/env python3
"""Source regression tripwires; these do not prove Android runtime behavior."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
src = root / 'app/src/main/java/com/baseer/bwork/legacy'
main = (src / 'MainActivity.java').read_text()
loader = (src / 'ImagePreviews.java').read_text()
view = (src / 'ImagePreviewView.java').read_text()
policy = (src / 'ImagePreviewPolicy.java').read_text()
attachments = (src / 'AttachmentSupport.java').read_text()
checks = 0

def check(value, label):
    global checks
    assert value, label
    checks += 1

def method(text, signature):
    start = text.index(signature)
    start = text.index('{', start)
    depth = 1
    for i in range(start + 1, len(text)):
        if text[i] == '{': depth += 1
        elif text[i] == '}': depth -= 1
        if depth == 0: return text[start + 1:i]
    raise AssertionError('Unbalanced method: ' + signature)

card = method(main, 'private View attachmentCard(')
bubble = method(main, 'private View messageBubble(')
decode = method(loader, 'static Bitmap decode(Context')
legacy = method(loader, 'static Bitmap decodeLegacy(')
load = method(loader, 'Request load(')
refresh = method(view, 'private void refreshVisibility(')
detach = method(view, 'protected void onDetachedFromWindow(')
result = method(main, 'protected void onActivityResult(')
check('BitmapFactory' not in main and 'loadImage(' not in main and 'ImageDecoder' not in main,
      'Activity has no synchronous image decoder or old loadImage helper')
check('new ImagePreviewView(' in card and 'photo.setLayoutParams(p(width, ImagePreviewPolicy.boundedHeight(' in card,
      'Image attachment OUTER view has explicit width/height before decode')
check('ImagePreviewPolicy.boundedWidth(windowWidth(), density, large)' in card,
      'Card width is bounded using current Activity window')
check('attachment.setOnLongClickListener' in bubble and 'showMessageActions(m)' in bubble,
      'Image attachment retains message long-press action path')
check('decode(context, file, target)' in load and 'worker.submit(' in load,
      'Native image decode remains submitted to worker')
check('Looper.myLooper() == Looper.getMainLooper()' in decode and 'throw new IllegalStateException' in decode,
      'Direct full decode refuses main-thread use')
check(decode.index('AttachmentSupport.requirePrivateFile') < decode.index('Modern.decode'),
      'Confinement and exact-size validation precede native decode')
check('Build.VERSION.SDK_INT >= 28' in decode and 'decodeLegacy(file, target)' in decode,
      'API 26 fallback remains reachable')
check('decoder.setTargetSize(' in loader and 'ImagePreviewPolicy.fit(' in loader
      and 'ImageDecoder.ALLOCATOR_SOFTWARE' in loader and 'setOnPartialImageListener(error -> false)' in loader,
      'Modern decoder requests bounded software bitmap and rejects partial images')
check('options.inJustDecodeBounds = true' in legacy and 'ImagePreviewPolicy.sampleSize(' in legacy
      and legacy.index('sampleSize(') < legacy.index('options.inJustDecodeBounds = false'),
      'Legacy decoder calculates sampled allocation from header first')
for orientation in ['FLIP_HORIZONTAL','ROTATE_180','FLIP_VERTICAL','TRANSPOSE','ROTATE_90','TRANSVERSE','ROTATE_270']:
    check('ExifInterface.ORIENTATION_' + orientation in legacy, 'Legacy EXIF transformation preserved: ' + orientation)
check('MAX_PENDING = 32' in loader and 'new ArrayBlockingQueue<>(MAX_PENDING)' in loader
      and 'pending.size() + detailPending.size() >= MAX_PENDING' in load and 'pending.get(key)' in load,
      'Decoder requests are bounded and deduplicated')
check('CACHE_BYTES = 16 * 1024 * 1024' in loader and 'getAllocationByteCount()' in loader,
      'Memory cache is byte bounded')
check('pending.get(key) != job' in loader and 'job.task.cancel(true)' in loader and 'worker.remove(' in loader,
      'Cancellation fences stale worker callbacks and removes queued tasks')
check('token != generation || !isAttachedToWindow()' in refresh and 'clearRequest(); file = attachment' in view,
      'Rebound/detached view rejects stale results')
check('getGlobalVisibleRect(visible)' in view and 'if (!visibleNow())' in refresh
      and 'clearRequest(); showWaiting();' in refresh,
      'Nonvisible previews release their display reference/request')
check('clearRequest(); showWaiting();' in detach and 'image.setImageDrawable(null)' in method(view, 'private void showWaiting(')
      and 'removeOnScrollChangedListener' in detach and 'removeOnGlobalLayoutListener' in detach,
      'Detach clears bitmap, request and listeners')
check('ImageView.ScaleType.FIT_CENTER' in view and 'CENTER_CROP' not in view,
      'Preview displays complete uncropped image')
check('image_preview_loading' in view and 'R.string.ui_308' in view and 'status.setVisibility(VISIBLE)' in refresh,
      'Loading and unavailable states are persistent visible text')
check(bool(re.search(r'new ImagePreviewView\(this, \w+, imagePreviews, 1[0-9]{2}, true\)', main)),
      'Draft thumbnail uses bounded async preview path')
check('imagePreviews.close()' in main, 'Activity destruction releases loader executor/cache')
check('AttachmentSupport.requirePrivateFile(this, photo)' in result and 'Collections.singletonList(photo)' in result,
      'Camera result validates original file and attaches without recompression')
check('AttachmentSupport.importUri(' in main and 'AttachmentSupport.saveToUri(' in main,
      'Gallery/share import and explicit export retain original-byte helper paths')
check('copyLimited(input, output, limit)' in attachments and 'copyLimited(input, output, attachment.size)' in attachments,
      'Import/export stream original bytes')
check(not re.search(r'\.compress\s*\(|FileOutputStream|openOutputStream', loader + view),
      'Preview code never compresses or writes original attachment bytes')
check('(long)width * height' in policy, 'Source pixel count promotes before multiplication')
for locale in ['values','values-ar','values-en']:
    check('name="image_preview_loading"' in (root / 'app/src/main/res' / locale / 'strings.xml').read_text(),
          'Loading-state localization exists: ' + locale)
check('catch (AttachmentSupport.SourceUnavailableException unavailable)' in loader and 'sourceMissing' in loader,
      'Missing originals are not silently presented as codec failures')
check('result.sourceMissing ? R.string.image_original_missing' in view,
      'Missing original has explicit localized preview guidance')
for locale in ['values','values-ar','values-en']:
    catalogue = (root / 'app/src/main/res' / locale / 'strings.xml').read_text()
    check('name="image_original_missing"' in catalogue and 'the original file is saved' not in catalogue
          and 'والملف الأصلي محفوظ' not in catalogue,
          'Missing-state translation exists without false saved-original claim: ' + locale)
check('if (composer.getMaxLines() != maxComposerLines) composer.setMaxLines(maxComposerLines)' in main,
      'Root layout does not unconditionally invalidate composer maxLines')
check('bar.getPaddingTop() != verticalPadding' in main and 'bar.getPaddingBottom() != verticalPadding' in main,
      'Root layout updates composer bar padding only when changed')
print(f'PASS {checks} image source-contract tripwires; Android runtime NOT executed')
