import createClient from 'openapi-fetch';
import type { components, paths } from './schema';

export type Schemas = components['schemas'];

/** The typed client generated from the frozen OpenAPI contract (schema.d.ts). */
export const api = createClient<paths>({
  baseUrl: typeof window === 'undefined' ? 'http://127.0.0.1' : window.location.origin,
});

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, title: string) {
    super(title);
    this.status = status;
  }
}

/** Problem bodies carry a stable title only; never show anything else from the server. */
export function problemMessage(status: number, problemTitle: string | undefined): string {
  if (status === 401) return 'Not signed in. For local development start the server with TRACE_DEV_AUTH=1.';
  if (status === 404) return 'Not found: this case has no built version yet, or the id is wrong.';
  return problemTitle ?? `Request failed (${status}).`;
}

export function unwrap<T>(
  result: { data?: T | undefined; error?: { title?: string } | undefined; response: Response },
): T {
  if (!result.response.ok || result.data === undefined) {
    throw new ApiError(result.response.status, problemMessage(result.response.status, result.error?.title));
  }
  return result.data;
}
