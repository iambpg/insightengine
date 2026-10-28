import { describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/apiError';
import { describeLoadError } from '@/lib/loadError';

describe('describeLoadError', () => {
  it('sends a signed-out session to the login screen', () => {
    const failure = describeLoadError(new ApiError(401, 'unauthorized', 'login required'), 'this device');
    expect(failure.signedOut).toBe(true);
    expect(failure.text).toBe('You are signed out - sign in');
  });

  it('keeps a 403 message', () => {
    const failure = describeLoadError(new ApiError(403, 'forbidden', 'Device CLI is limited to Administrators and Engineers'), 'the command');
    expect(failure.text).toContain('Administrators');
    expect(failure.signedOut).toBe(false);
  });

  it('uses the server message for a missing device', () => {
    const failure = describeLoadError(new ApiError(404, 'not_found', 'unknown device'), 'this device');
    expect(failure.text).toBe('unknown device');
  });

  it('names a 5xx failure instead of a connection problem', () => {
    const failure = describeLoadError(new ApiError(502, 'upstream_unavailable', 'NetBox is not reachable'), 'this device');
    expect(failure.text).toContain('HTTP 502');
    expect(failure.text).not.toContain('Check your connection');
  });

  it('reserves the connection sentence for a network failure', () => {
    const failure = describeLoadError(new ApiError(0, 'network', 'down'), 'this device');
    expect(failure.text).toContain('did not respond');
    const plain = describeLoadError(new Error('boom'), 'this device');
    expect(plain.text).toContain('did not respond');
  });

  it('shows the credentials message instead of a generic failure', () => {
    const failure = describeLoadError(
      new ApiError(409, 'credentials_not_configured', 'CLI credentials are not set for this device. An Administrator or Engineer must save them before a command can run.'),
      'the command'
    );
    expect(failure.text).toContain('CLI credentials are not set');
  });
});
