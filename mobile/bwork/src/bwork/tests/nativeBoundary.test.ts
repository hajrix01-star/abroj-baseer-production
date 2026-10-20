import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { actorPattern, mediaFilePattern, nativeSessionOptions, retainNativeFile, scopePattern, trustedMedia, validThumbnail } from '../core/nativeBoundary.ts';
import type { History } from '../core/ChatEngine.ts';

const media = { id: 70, kind: 'file', mime: 'application/pdf', name: 'approved.pdf', size: 1024, sha256: 'a'.repeat(64) };
const history: History = { api_version: 2, next_before_id: null, messages: [{ id: 1, author_user_id: 7, author_name: 'A', text: '', created_at: '', media }] };
test('native descriptor only selects ID; trusted room history owns byte metadata', () => {
  const trusted = trustedMedia(history, { id: 70, mime: 'image/png', sha256: 'b'.repeat(64), size: 1, name: 'arbitrary.png' });
  assert.deepEqual(trusted, media);
  assert.throws(() => trustedMedia(history, { id: 80 }), { code: 'media_room_mismatch' });
  assert.throws(() => trustedMedia(history, { id: '70' }), { code: 'invalid_attachment' });
});
test('unknown or malformed trusted byte metadata is rejected', () => {
  for (const bad of [{ ...media, sha256: 'bad' }, { ...media, size: 0 }, { ...media, size: 10 * 1024 * 1024 + 1 }]) {
    const page = { ...history, messages: [{ ...history.messages[0]!, media: bad }] };
    assert.throws(() => trustedMedia(page, { id: 70 }), { code: 'media_room_mismatch' });
  }
});
test('native cache cleanup preserves only permitted scope and needed stages', () => {
  const base = { filename: 'media-70.pdf', mode: 'snapshot' as const, validIdentity: true, matchingScope: true, mediaRight: true, sendRight: true, pending: false, reserved: false };
  assert.equal(retainNativeFile(base), true);
  assert.equal(retainNativeFile({ ...base, matchingScope: false }), false);
  assert.equal(retainNativeFile({ ...base, mediaRight: false }), false);
  assert.equal(retainNativeFile({ ...base, mode: 'logout' }), false);
  assert.equal(retainNativeFile({ ...base, filename: 'stage-id.pdf', pending: true }), true);
  assert.equal(retainNativeFile({ ...base, filename: 'stage-id.pdf', pending: true, mediaRight: false }), false);
  assert.equal(retainNativeFile({ ...base, filename: 'stage-id.pdf', pending: true, matchingScope: false }), false);
  assert.equal(retainNativeFile({ ...base, filename: 'stage-id.pdf', reserved: true }), true);
  assert.equal(retainNativeFile({ ...base, filename: 'stage-id.pdf', mode: 'logout', pending: true }), false);
  assert.equal(retainNativeFile({ ...base, filename: 'stage-id.pdf', validIdentity: false, matchingScope: false }), true);
  assert.equal(retainNativeFile({ ...base, filename: 'stage-id.pdf', mode: 'cacheOnly', matchingScope: false }), true);
});
test('native destructive target grammar excludes traversal and broad roots', () => {
  assert.equal(actorPattern.test('a'.repeat(64)), true);
  for (const path of ['../', '', 'a'.repeat(64) + '/other']) assert.equal(actorPattern.test(path), false);
  assert.equal(scopePattern.test('c1-r11-m21'), true);
  for (const path of ['c0-r11-m21', 'c1-r11-m21/../', '../', 'c1-r11']) assert.equal(scopePattern.test(path), false);
  assert.equal(mediaFilePattern.test('stage-uuid.pdf'), true);
  for (const path of ['../secret', 'stage-../../secret', 'other.pdf', '']) assert.equal(mediaFilePattern.test(path), false);
});
test('installed native dependency enforces no-follow and shared Android cookie jar', () => {
  assert.deepEqual(nativeSessionOptions, { followRedirect: false, timeout: 30000, trusty: false });
  const base = new URL('../../../', import.meta.url);
  const nativeImpl = readFileSync(new URL('node_modules/react-native-blob-util/android/src/main/java/com/ReactNativeBlobUtil/ReactNativeBlobUtilImpl.java', base), 'utf8');
  const nativeRequest = readFileSync(new URL('node_modules/react-native-blob-util/android/src/main/java/com/ReactNativeBlobUtil/ReactNativeBlobUtilReq.java', base), 'utf8');
  assert.match(nativeImpl, /OkHttpClientProvider\.getOkHttpClient\(\)/);
  assert.match(nativeImpl, /mCookieJarContainer\.setCookieJar\(new JavaNetCookieJar\(mCookieHandler\)\)/);
  assert.match(nativeRequest, /clientBuilder\.followRedirects\(options\.followRedirect\)/);
  assert.match(nativeRequest, /clientBuilder\.followSslRedirects\(options\.followRedirect\)/);
});
test('runtime source uses no-follow client on all network paths with scoped history and hash checks', () => {
  const runtime = readFileSync(new URL('../runtime.ts', import.meta.url), 'utf8');
  assert.match(runtime, /BlobUtil\.config\(\{ \.\.\.nativeSessionOptions/);
  assert.doesNotMatch(runtime, /\bawait fetch\(/);
  assert.match(runtime, /getEngine\(\)\.mediaAssociation\(room, Number\(descriptor\.id\)\)/);
  assert.match(runtime, /cached\.size === expected\.bytes && await hashFile\(path\) === expected\.sha256/);
  assert.match(runtime, /cachedLease\(`\$\{directory\}media-\$\{media\.id\}\$\{extension\}`, \{ bytes: media\.size, sha256: media\.sha256 \}\)/);
  assert.match(runtime, /digest !== media\.sha256/);
  assert.doesNotMatch(runtime, /CookieManager|\.getCookies\(|\.getCookie\(/);
});
test('thumbnail JPEG parser bounds dimensions, structure, type and length', () => {
  const jpeg = Buffer.from([255,216,255,192,0,11,8,0,1,0,1,1,1,17,0,255,218,0,8,1,1,0,0,63,0,1,255,217]);
  assert.equal(validThumbnail(jpeg.toString('binary')), true);
  for (const bytes of [Buffer.from('not JPEG'), Buffer.concat([jpeg, Buffer.alloc(128 * 1024)]),
    (() => { const bad = Buffer.from(jpeg); bad[7] = 1; bad[8] = 1; return bad; })(), jpeg.subarray(0, jpeg.length - 1)])
    assert.equal(validThumbnail(bytes.toString('binary')), false);
});
