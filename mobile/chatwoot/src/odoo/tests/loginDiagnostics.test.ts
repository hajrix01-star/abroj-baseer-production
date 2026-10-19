import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loginDiagnostic, nativeSessionTrace, networkFailure } from '../core/loginDiagnostics.ts';

test('native network hints classify known failures without returning native text', () => {
  assert.equal(
    networkFailure(new Error('Unable to resolve host private.example: no address')),
    'DNS',
  );
  assert.equal(networkFailure(new Error('SSLHandshakeException: Trust anchor missing')), 'TLS');
  assert.equal(networkFailure(new Error('SocketTimeoutException: timeout')), 'TIMEOUT');
  assert.equal(networkFailure(new Error('Failed to connect: ECONNREFUSED')), 'CONNECT');
  assert.equal(networkFailure(new Error('private-cookie password=secret')), 'OTHER');
});

test('login diagnostic only exposes allowlisted phase, failure and HTTP status', () => {
  assert.equal(
    loginDiagnostic({
      code: 'connection_failed',
      loginStage: 'session_close',
      networkFailure: 'DNS',
    }),
    'LOGIN3-CLOSE-DNS-0',
  );
  assert.equal(
    loginDiagnostic({ code: 'redirect_denied', loginStage: 'bootstrap', status: 303 }),
    'LOGIN3-PROFILE-REDIRECT-303',
  );
  assert.equal(
    loginDiagnostic({ code: 'native_response_missing', loginStage: 'authenticate' }),
    'LOGIN3-AUTH-NATIVE-0',
  );
  assert.equal(
    loginDiagnostic({
      code: 'secret-cookie',
      loginStage: 'password=secret',
      networkFailure: 'private.example',
      status: 'secret',
    }),
    'LOGIN3-LOCAL-OTHER-0',
  );
  assert.equal(
    loginDiagnostic(new Error('password=secret session_id=private')),
    'LOGIN3-LOCAL-OTHER-0',
  );
});

test('native session observations accept five bits only and never export cookie material', () => {
  const valid = 'I1A1S1M1L1';
  assert.equal(nativeSessionTrace(valid), valid);
  assert.equal(loginDiagnostic({ code: 'redirect_denied', loginStage: 'bootstrap', status: 303,
    sessionTrace: valid }), 'LOGIN3-PROFILE-REDIRECT-303-I1A1S1M1L1');
  for (const value of [null, 123, {}, 'session_id=secret', `${valid}\n`, `${valid}-password=secret`,
    'I2A1S1M1L1', 'I1S1M1L1']) {
    assert.equal(nativeSessionTrace(value), undefined);
    assert.equal(loginDiagnostic({ code: 'redirect_denied', loginStage: 'bootstrap', status: 303,
      sessionTrace: value }), 'LOGIN3-PROFILE-REDIRECT-303');
  }
  assert.equal(loginDiagnostic({ code: 'redirect_denied', loginStage: 'authenticate', status: 303,
    sessionTrace: valid }), 'LOGIN3-AUTH-REDIRECT-303');
});
