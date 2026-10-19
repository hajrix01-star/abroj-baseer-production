/** Support codes only: never return raw native messages, URLs, credentials or responses. */
export type LoginStage = 'session_close' | 'authenticate' | 'bootstrap' | 'rooms' | 'storage';
export type NetworkFailure = 'DNS' | 'TLS' | 'TIMEOUT' | 'CONNECT' | 'OTHER';

/** Native-only observations cross the bridge as five bits, never cookie data. */
export function nativeSessionTrace(value: unknown): string | undefined {
  return typeof value === 'string' && /^I[01]A[01]S[01]M[01]L[01]$/.test(value)
    ? value
    : undefined;
}

export function networkFailure(error: unknown): NetworkFailure {
  const message = error instanceof Error ? error.message : '';
  if (/unable to resolve host|unknownhost|enotfound|no address associated/i.test(message))
    return 'DNS';
  if (/ssl|certificate|trust anchor|certpath/i.test(message)) return 'TLS';
  if (/timed?\s*out|timeout|etimedout/i.test(message)) return 'TIMEOUT';
  if (/failed to connect|connection refused|econnrefused|no route to host/i.test(message))
    return 'CONNECT';
  return 'OTHER';
}

const stages: Record<LoginStage, string> = {
  session_close: 'CLOSE',
  authenticate: 'AUTH',
  bootstrap: 'PROFILE',
  rooms: 'ROOMS',
  storage: 'SAVE',
};
const failures: Record<string, string> = {
  connection_failed: 'NETWORK',
  redirect_denied: 'REDIRECT',
  native_response_missing: 'NATIVE',
  invalid_response: 'JSON',
  identity_mismatch: 'SCOPE',
  invalid_rooms: 'ROOMS',
  authentication_failed: 'AUTH',
  login_failed: 'AUTH',
  mfa_required: 'MFA',
  session_expired: 'SESSION',
  unauthenticated: 'SESSION',
  forbidden: 'DENIED',
  request_failed: 'HTTP',
  stale_session: 'STALE',
};
export function loginDiagnostic(error: unknown): string {
  const value =
    error && typeof error === 'object'
      ? (error as {
          code?: unknown;
          status?: unknown;
          loginStage?: unknown;
          networkFailure?: unknown;
          sessionTrace?: unknown;
        })
      : {};
  const stage =
    typeof value.loginStage === 'string' && Object.prototype.hasOwnProperty.call(stages, value.loginStage)
      ? stages[value.loginStage as LoginStage]
      : 'LOCAL';
  let failure =
    typeof value.code === 'string' && Object.prototype.hasOwnProperty.call(failures, value.code)
      ? failures[value.code]
      : 'OTHER';
  if (
    value.code === 'connection_failed' &&
    typeof value.networkFailure === 'string' &&
    ['DNS', 'TLS', 'TIMEOUT', 'CONNECT', 'OTHER'].includes(value.networkFailure)
  )
    failure = value.networkFailure;
  const status =
    typeof value.status === 'number' &&
    Number.isInteger(value.status) &&
    value.status >= 100 &&
    value.status <= 599
      ? value.status
      : 0;
  const trace = stage === 'PROFILE' ? nativeSessionTrace(value.sessionTrace) : undefined;
  return `LOGIN3-${stage}-${failure}-${status}${trace ? `-${trace}` : ''}`;
}
