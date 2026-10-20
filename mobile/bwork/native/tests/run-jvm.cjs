// No downloads/Gradle/JUnit. Compile against the installed Android/RN/OkHttp artifacts.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const {contract,artifact}=require('../sdk.cjs');
if(require('../../node_modules/react-native/package.json').version!==contract.reactNative)throw Error('Installed React Native differs from native proof SDK contract');
const jdk = process.env.JAVA_HOME || 'C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot';
const android = process.env.ANDROID_HOME || 'D:/Codex/AndroidSdk';
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'bwork-native-cookie-'));
const bin = name => path.join(jdk, 'bin', name + (process.platform === 'win32' ? '.exe' : ''));
const react = artifact('react');
execFileSync(bin('jar'), ['xf', react, 'classes.jar'], { cwd: temp, stdio: 'inherit' });
const cp = [path.join(temp, 'classes.jar'), path.join(android, 'platforms/android-36/android.jar'),
  ...contract.session.filter(key=>key!=='react').map(artifact)].join(path.delimiter);
const source = path.join(__dirname, '../android/com/baseer/bwork/session');
// Compile the actual installed BlobUtil inner interceptor, with only Android response wrappers
// replaced by dependency-free delegates. Preserve its captured req, catches and second proceed.
const blobSource = fs.readFileSync(path.join(__dirname, '../../node_modules/react-native-blob-util/android/src/main/java/com/ReactNativeBlobUtil/ReactNativeBlobUtilReq.java'), 'utf8');
const blobStart = blobSource.indexOf('clientBuilder.addInterceptor(new Interceptor() {');
const blobRetry = blobSource.indexOf('return chain.proceed(chain.request());', blobStart);
const blobEnd = blobSource.indexOf('\n            });', blobRetry);
if (blobStart < 0 || blobRetry < 0 || blobEnd < 0) throw new Error('Installed BlobUtil interceptor template changed');
const inner = blobSource.slice(blobStart, blobEnd + '\n            });'.length);
const captured = path.join(temp, 'CapturedBlobUtilInterceptor.java');
fs.writeFileSync(captured, `package com.baseer.bwork.session;
import java.io.*; import java.net.*; import okhttp3.*; import okio.BufferedSource;
public final class CapturedBlobUtilInterceptor {
 @interface NonNull {} enum Mode { KeepInMemory, FileStorage }
 Mode responseType=Mode.KeepInMemory; String taskId="synthetic",destPath="synthetic"; boolean timeout;
 static class Options { boolean increment,overwrite; } Options options=new Options();
 static class ReactNativeBlobUtilImpl { static Object RCTContext; }
 static class ReactNativeBlobUtilDefaultResp extends ResponseBody {
  final ResponseBody body; ReactNativeBlobUtilDefaultResp(Object c,String id,ResponseBody b,boolean i){body=b;}
  public MediaType contentType(){return body.contentType();} public long contentLength(){return body.contentLength();}
  public BufferedSource source(){return body.source();}
 }
 static class ReactNativeBlobUtilFileResp extends ReactNativeBlobUtilDefaultResp {
  ReactNativeBlobUtilFileResp(Object c,String id,ResponseBody b,String p,boolean o){super(c,id,b,o);}
 }
 public void install(OkHttpClient.Builder clientBuilder, final Request req) { ${inner} }
}`);
execFileSync(bin('javac'), ['-encoding', 'UTF-8', '-cp', cp, '-d', temp,
  ...['CommitCookieHandler.java', 'OriginCookieJar.java', 'BaseerSessionNetworking.java', 'SessionDiagnostics.java'].map(file => path.join(source, file)),
  path.join(__dirname, 'SessionCookieHarness.java'), path.join(__dirname, 'SessionDiagnosticsHarness.java'), path.join(__dirname, 'AvatarReplayHarness.java'), captured], { stdio: 'inherit' });
execFileSync(bin('java'), ['-ea', '-cp', temp + path.delimiter + cp, 'com.baseer.bwork.session.SessionCookieHarness'], { stdio: 'inherit' });
execFileSync(bin('java'), ['-ea', '-cp', temp + path.delimiter + cp, 'com.baseer.bwork.session.SessionDiagnosticsHarness'], { stdio: 'inherit' });
execFileSync(bin('java'), ['-ea', '-cp', temp + path.delimiter + cp, 'com.baseer.bwork.session.AvatarReplayHarness'], { stdio: 'inherit' });
console.log('Compiled production Android adapter with installed RN and android-36 classes. Temporary classes: ' + temp);
