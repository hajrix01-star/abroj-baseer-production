import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loginDiagnostic, networkFailure } from '../core/loginDiagnostics.ts';

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
    'LOGIN2-CLOSE-DNS-0',
  );
  assert.equal(
    loginDiagnostic({ code: 'redirect_denied', loginStage: 'bootstrap', status: 303 }),
    'LOGIN2-PROFILE-REDIRECT-303',
  );
  assert.equal(
    loginDiagnostic({ code: 'native_response_missing', loginStage: 'authenticate' }),
    'LOGIN2-AUTH-NATIVE-0',
  );
  assert.equal(
    loginDiagnostic({
      code: 'secret-cookie',
      loginStage: 'password=secret',
      networkFailure: 'private.example',
      status: 'secret',
    }),
    'LOGIN2-LOCAL-OTHER-0',
  );
  assert.equal(
    loginDiagnostic(new Error('password=secret session_id=private')),
    'LOGIN2-LOCAL-OTHER-0',
  );
});
