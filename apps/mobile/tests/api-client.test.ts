/**
 * The API client.
 *
 * These are the tests that matter most in the app. The client is the one place
 * that knows how to authenticate a request and how to unwrap a failure, so a
 * bug here is a bug on every screen at once.
 */

import {
  API_BASE_URL,
  ApiError,
  buildUrlForTest,
  configureClient,
  errorMessage,
  isApiError,
  request,
} from '@/api/client';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const errorBody = {
  error: {
    code: 'business_rule_violation',
    message: 'That slot is already taken. Pick another time.',
    details: null,
  },
};

describe('ApiError', () => {
  it('exposes the server message, status and code', () => {
    const error = new ApiError('Nope.', 400, 'validation_error');

    expect(error.message).toBe('Nope.');
    expect(error.status).toBe(400);
    expect(error.code).toBe('validation_error');
  });

  it('separates field errors from the general message', () => {
    const error = new ApiError('Invalid', 400, 'validation_error', {
      email: ['This field is required.'],
    });

    expect(error.fieldErrors).toEqual({ email: ['This field is required.'] });
  });

  it('reports no field errors when details is a list', () => {
    const error = new ApiError('Invalid', 400, 'validation_error', ['Bad']);

    expect(error.fieldErrors).toEqual({});
  });

  it('distinguishes a network failure from a server response', () => {
    expect(new ApiError('x', 0, 'network_error').isNetworkError).toBe(true);
    expect(new ApiError('x', 500, 'server_error').isNetworkError).toBe(false);
    expect(new ApiError('x', 401, 'x').isUnauthorized).toBe(true);
  });
});

describe('request', () => {
  beforeEach(() => {
    configureClient({ getToken: () => 'test-token', onUnauthorized: () => undefined });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('returns the parsed body on success', async () => {
    jest.spyOn(global, 'fetch').mockResolvedValue(jsonResponse({ id: 1 }));

    await expect(request('/me/')).resolves.toEqual({ id: 1 });
  });

  it('sends the token as an Authorization header', async () => {
    const fetchSpy = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue(jsonResponse({ ok: true }));

    await request('/me/');

    const [, init] = fetchSpy.mock.calls[0]!;
    expect((init!.headers as Record<string, string>).Authorization).toBe('Token test-token');
  });

  it('omits the header when signed out', async () => {
    configureClient({ getToken: () => null });
    const fetchSpy = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue(jsonResponse({ ok: true }));

    await request('/me/');

    const [, init] = fetchSpy.mock.calls[0]!;
    expect((init!.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('unwraps the error envelope', async () => {
    jest.spyOn(global, 'fetch').mockResolvedValue(jsonResponse(errorBody, 400));

    await expect(request('/bookings/new/', { method: 'POST' })).rejects.toMatchObject({
      status: 400,
      code: 'business_rule_violation',
      message: 'That slot is already taken. Pick another time.',
    });
  });

  it('falls back to a status message when the body is not ours', async () => {
    // A proxy or load balancer error page: HTML, not our envelope.
    jest
      .spyOn(global, 'fetch')
      .mockResolvedValue(new Response('<html>502</html>', { status: 502 }));

    await expect(request('/me/')).rejects.toMatchObject({
      status: 502,
      message: expect.stringContaining('502'),
    });
  });

  it('turns a connection failure into a readable network error', async () => {
    jest.spyOn(global, 'fetch').mockRejectedValue(new TypeError('Network request failed'));

    await expect(request('/me/')).rejects.toMatchObject({
      status: 0,
      isNetworkError: true,
    });
  });

  it('lets an abort through untouched', async () => {
    const abort = new Error('Aborted');
    abort.name = 'AbortError';
    jest.spyOn(global, 'fetch').mockRejectedValue(abort);

    await expect(request('/providers/', {})).rejects.toBe(abort);
  });

  it('signs the user out exactly once, wherever a 401 surfaces', async () => {
    const onUnauthorized = jest.fn();
    configureClient({ getToken: () => 'stale', onUnauthorized });
    jest.spyOn(global, 'fetch').mockResolvedValue(
      jsonResponse({ error: { code: 'not_authenticated', message: 'No token', details: null } }, 401),
    );

    await expect(request('/me/')).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('does not sign the user out for the webhook, which has no token', async () => {
    const onUnauthorized = jest.fn();
    configureClient({ getToken: () => null, onUnauthorized });
    jest.spyOn(global, 'fetch').mockResolvedValue(jsonResponse({}, 400));

    await expect(
      request('/payments/webhook/', { method: 'POST', skipAuth: true }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it('resolves undefined for 204 so callers do not parse an empty body', async () => {
    jest.spyOn(global, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));

    await expect(request('/me/', { method: 'DELETE' })).resolves.toBeUndefined();
  });

  it('lets FormData set its own multipart boundary', async () => {
    const fetchSpy = jest.spyOn(global, 'fetch').mockResolvedValue(jsonResponse({}));

    const form = new FormData();
    form.append('display_name', 'Sharp Cuts');
    await request('/me/shop/', { method: 'PUT', body: form });

    const [, init] = fetchSpy.mock.calls[0]!;
    const headers = init!.headers as Record<string, string>;
    // Setting Content-Type by hand strips the boundary and the upload silently
    // fails to parse on the server.
    expect(headers['Content-Type']).toBeUndefined();
  });

  it('JSON-encodes a plain object body', async () => {
    const fetchSpy = jest.spyOn(global, 'fetch').mockResolvedValue(jsonResponse({}));

    await request('/auth/login/', { method: 'POST', body: { identifier: 'jane' } });

    const [, init] = fetchSpy.mock.calls[0]!;
    expect(init!.body).toBe('{"identifier":"jane"}');
    expect((init!.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });
});

describe('buildUrlForTest', () => {
  it('drops empty values rather than sending ?a=&b=', () => {
    const url = buildUrlForTest('/providers/', {
      lat: 28.6,
      lng: undefined,
      radius_km: null,
      service_type: '',
      open_now: false,
    });

    // false is a real value; undefined, null and '' are not.
    expect(url).toContain('lat=28.6');
    expect(url).toContain('open_now=false');
    expect(url).not.toContain('lng=');
    expect(url).not.toContain('radius_km=');
    expect(url).not.toContain('service_type=');
  });

  it('joins arrays with commas, which is what the API expects', () => {
    const url = buildUrlForTest('/providers/', { services: ['Haircut', 'Beard trim'] });

    expect(url).toContain('services=Haircut%2CBeard+trim');
  });

  it('skips an empty array rather than sending services=', () => {
    expect(buildUrlForTest('/providers/', { services: [] })).not.toContain('services=');
  });
});

describe('errorMessage', () => {
  it('uses the server message for an API error', () => {
    expect(errorMessage(new ApiError('Nope.', 400, 'x'))).toBe('Nope.');
  });

  it('falls back for anything else', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom');
    expect(errorMessage({}, 'Fallback.')).toBe('Fallback.');
    expect(errorMessage(null)).toBe('Something went wrong.');
  });

  it('recognises its own errors', () => {
    expect(isApiError(new ApiError('x', 400, 'y'))).toBe(true);
    expect(isApiError(new Error('x'))).toBe(false);
  });
});

describe('base url', () => {
  it('never ends in a slash, so paths do not double up', () => {
    expect(API_BASE_URL.endsWith('/')).toBe(false);
  });
});