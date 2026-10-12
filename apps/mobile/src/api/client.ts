/**
 * The HTTP client.
 *
 * Deliberately hand-rolled on `fetch` rather than axios. The old apps used
 * axios and ended up with a global interceptor chain that any caller could
 * bypass by forgetting to spread its config; here every request goes through one
 * function, so there is nowhere for the auth header or the error unwrapping to
 * be skipped.
 */

import type { ApiErrorBody } from '@/types/api';

export const API_BASE_URL = (
  process.env.EXPO_PUBLIC_API_URL ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '');

const API_ROOT = `${API_BASE_URL}/api/v1`;

/** A failed request, carrying the server's own message where there is one. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorBody['error']['details'];

  constructor(
    message: string,
    status: number,
    code: string,
    details: ApiErrorBody['error']['details'] = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Field-level messages, for rendering next to inputs. */
  get fieldErrors(): Record<string, string[]> {
    if (this.details && !Array.isArray(this.details)) return this.details;
    return {};
  }

  /** True when the request never reached the server. */
  get isNetworkError(): boolean {
    return this.status === 0;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

/** Supplies the bearer token. Set by the auth store on boot. */
type TokenProvider = () => string | null;

/** Called when the server rejects our token, so the app can sign out. */
type UnauthorizedHandler = () => void;

let getToken: TokenProvider = () => null;
let onUnauthorized: UnauthorizedHandler = () => {};

export function configureClient(options: {
  getToken?: TokenProvider;
  onUnauthorized?: UnauthorizedHandler;
}): void {
  if (options.getToken) getToken = options.getToken;
  if (options.onUnauthorized) onUnauthorized = options.onUnauthorized;
}

export type QueryParams = Record<
  string,
  string | number | boolean | undefined | null | (string | number)[]
>;

function buildUrl(path: string, params?: QueryParams): string {
  const url = `${API_ROOT}${path}`;
  if (!params) return url;

  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      if (value.length) search.set(key, value.join(','));
    } else {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `${url}?${query}` : url;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  params?: QueryParams;
  /** Set for endpoints the server calls with a signature instead of a token. */
  skipAuth?: boolean;
  signal?: AbortSignal;
  /**
   * Reuse an idempotency key across retries of one logical operation.
   *
   * Left unset, a key is generated per request — which protects against a
   * *resend of the same request* but not against a retry, because a retry is a
   * new request. Callers that the query layer might retry pass a stable key so
   * both cases land on the same record.
   */
  idempotencyKey?: string;
}

/**
 * A key that identifies one logical operation, not one HTTP request.
 *
 * Without it, a retried payment request is a second chance to charge.
 */
export function newIdempotencyKey(): string {
  const random = Math.random().toString(36).slice(2, 12);
  return `${Date.now().toString(36)}-${random}`;
}

async function readError(response: Response): Promise<ApiError> {
  let code = 'error';
  let message = `Request failed (${response.status})`;
  let details: ApiErrorBody['error']['details'] = null;

  try {
    const body = (await response.json()) as ApiErrorBody;
    if (body?.error) {
      code = body.error.code;
      message = body.error.message;
      details = body.error.details ?? null;
    }
  } catch {
    // A non-JSON body means something in front of the API returned it — a proxy
    // error page, say. The status-based message above is the useful one.
  }

  return new ApiError(message, response.status, code, details);
}

/**
 * Exposed for tests.
 *
 * Query-string assembly is where a missing filter becomes a silently wrong
 * request — `?lng=undefined` is truthy on the server and quietly widens a radius
 * search to the whole planet.
 */
export const buildUrlForTest = buildUrl;

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, params, skipAuth = false, signal, idempotencyKey } = options;

  const headers: Record<string, string> = { Accept: 'application/json' };

  // React Native's FormData sets its own multipart boundary. Setting
  // Content-Type by hand here is what made file uploads fail in the old apps.
  if (body !== undefined && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  if (!skipAuth) {
    const token = getToken();
    if (token) headers.Authorization = `Token ${token}`;
  }

  // Sent on every write. The server replays the first response for a repeated
  // key and refuses a repeated key with a different body — which is the whole
  // reason a retry of a payment is safe.
  if (method !== 'GET') {
    headers['Idempotency-Key'] = idempotencyKey ?? newIdempotencyKey();
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, params), {
      method,
      headers,
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    if (cause instanceof Error && cause.name === 'AbortError') throw cause;
    throw new ApiError(
      'Could not reach BarberShop. Check your connection and try again.',
      0,
      'network_error',
    );
  }

  if (response.status === 204) return undefined as T;

  if (!response.ok) {
    const error = await readError(response);
    // One place decides what an expired token means for the whole app. Callers
    // that each handled this separately is how the old apps ended up signed out
    // on some screens and stuck on others.
    if (error.isUnauthorized && !skipAuth) onUnauthorized();
    throw error;
  }

  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, params?: QueryParams, signal?: AbortSignal) =>
    request<T>(path, { params, signal }),
  post: <T>(path: string, body?: unknown, params?: QueryParams, idempotencyKey?: string) =>
    request<T>(path, { method: 'POST', body, params, idempotencyKey }),
  put: <T>(path: string, body?: unknown, idempotencyKey?: string) =>
    request<T>(path, { method: 'PUT', body, idempotencyKey }),
  patch: <T>(path: string, body?: unknown, idempotencyKey?: string) =>
    request<T>(path, { method: 'PATCH', body, idempotencyKey }),
  delete: <T>(path: string, idempotencyKey?: string) =>
    request<T>(path, { method: 'DELETE', idempotencyKey }),
};

/** True when the error is one the user can do something about. */
export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** A message safe to put in front of a user, whatever was thrown. */
export function errorMessage(error: unknown, fallback = 'Something went wrong.'): string {
  if (isApiError(error)) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}