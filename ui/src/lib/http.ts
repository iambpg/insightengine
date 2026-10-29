import { ApiError } from '@/lib/apiError';
import { readSession } from '@/lib/session';

interface RequestInitJson {
  method?: string;
  body?: unknown;
  form?: FormData;
}

export async function request<T>(path: string, init?: RequestInitJson): Promise<T> {
  const method = init?.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };
  const writing = method !== 'GET' && method !== 'HEAD';
  if (writing) {
    const token = readSession()?.csrfToken;
    if (token) headers['X-CSRF-Token'] = token;
  }
  let body: BodyInit | undefined;
  if (init?.form) {
    body = init.form;
  } else if (init?.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(init.body);
  }

  let response: Response;
  try {
    response = await fetch(path, { method, headers, body, credentials: 'include', cache: 'no-store' });
  } catch {
    throw new ApiError(
      0,
      'network',
      'The service did not respond. Check your connection and try again.'
    );
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new ApiError(
        response.status || 500,
        'bad_response',
        'The service returned a response that was not JSON.'
      );
    }
  }
  if (!response.ok) {
    throw errorFrom(response.status, data, response.statusText);
  }
  return data as T;
}

export function errorFrom(status: number, data: unknown, statusText: string): ApiError {
  const record = asRecord(data);
  if (record && Array.isArray(record.messages) && typeof record.ok === 'boolean') {
    return new ApiError(status, 'validation_failed', 'Validation failed.', record);
  }
  const error = asRecord(record?.error);
  return new ApiError(
    status,
    typeof error?.code === 'string' ? error.code : `http_${status}`,
    typeof error?.message === 'string' ? error.message : statusText || 'Request failed',
    error?.details
  );
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}
