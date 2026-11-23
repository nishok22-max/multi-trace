import createClient from 'openapi-fetch';
import type { components, paths } from './schema';

export type Schemas = components['schemas'];

export const CSRF_HEADER = 'X-TRACE-CSRF';
/** The typed contract requires the header on every write; pass this as `params.header`. */
export const CSRF = { 'X-TRACE-CSRF': '1' } as const;

/** The typed client generated from the frozen OpenAPI contract (schema.d.ts). Every write
 *  carries the CSRF header (the server refuses a write without it); cookies are same-origin only. */
export const api = createClient<paths>({
  baseUrl: typeof window === 'undefined' ? 'http://127.0.0.1' : window.location.origin,
  credentials: 'same-origin',
});

api.use({
  onRequest({ request }) {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) request.headers.set(CSRF_HEADER, '1');
    return request;
  },
});

export class ApiError extends Error {
  readonly status: number;
  readonly problemType: string | undefined;
  constructor(status: number, title: string, problemType?: string) {
    super(title);
    this.status = status;
    this.problemType = problemType;
  }
}

/** Problem bodies carry a stable title only; never show anything else from the server. */
export function problemMessage(status: number, problemTitle: string | undefined): string {
  if (status === 401) return 'Not signed in.';
  if (status === 403) return 'Your role does not allow this.';
  if (status === 404) return 'Not found: this case has no built version yet, or the id is wrong.';
  if (status === 429) return 'Too many requests. Wait a minute and try again.';
  return problemTitle ?? `Request failed (${status}).`;
}

export function unwrap<T>(result: {
  data?: T | undefined;
  error?: { title?: string; type?: string } | undefined;
  response: Response;
}): T {
  if (!result.response.ok || result.data === undefined) {
    throw new ApiError(
      result.response.status,
      problemMessage(result.response.status, result.error?.title),
      result.error?.type,
    );
  }
  return result.data;
}
