/**
 * Typed client for the MY-P1 control API.
 *
 * Every request carries the bearer token and a timeout. A phone loses its
 * network constantly — walking into a lift, switching wifi to cellular — so
 * a hung request is the normal case, not the exceptional one, and the UI
 * needs it to fail fast enough to show a stale badge rather than a spinner
 * that never resolves.
 */

import type {
  CandleSeries,
  Connection,
  ControlResult,
  FillRow,
  Health,
  Pnl,
  PositionDetail,
  Status,
} from './types';

const TIMEOUT_MS = 8000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly statusCode?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** True when the token is wrong — the UI sends the user back to setup. */
  get isAuthError(): boolean {
    return this.statusCode === 401;
  }
}

export function normaliseBaseUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '');
  if (!trimmed) throw new ApiError('Server address is required');
  if (!/^https?:\/\//i.test(trimmed)) return `http://${trimmed}`;
  return trimmed;
}

async function request<T>(
  connection: Connection,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(`${connection.baseUrl}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Authorization: `Bearer ${connection.token}`,
        'Content-Type': 'application/json',
        ...(init.headers ?? {}),
      },
    });

    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const body = await response.json();
        if (typeof body?.detail === 'string') detail = body.detail;
      } catch {
        // Non-JSON error body; the status-based message stands.
      }
      throw new ApiError(detail, response.status);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError('Timed out — is the bot reachable from this network?');
    }
    throw new ApiError('Cannot reach the bot. Check the address and your VPN.');
  } finally {
    clearTimeout(timer);
  }
}

const get = <T>(connection: Connection, path: string) =>
  request<T>(connection, path);

const post = <T>(connection: Connection, path: string) =>
  request<T>(connection, path, { method: 'POST' });

export const api = {
  health: (c: Connection) => get<Health>(c, '/api/health'),
  status: (c: Connection) => get<Status>(c, '/api/status'),
  position: (c: Connection) => get<PositionDetail>(c, '/api/position'),
  pnl: (c: Connection) => get<Pnl>(c, '/api/pnl'),
  fills: (c: Connection, limit = 25) =>
    get<{ fills: FillRow[] }>(c, `/api/fills?limit=${limit}`),
  candles: (c: Connection, limit = 100) =>
    get<CandleSeries>(c, `/api/candles?limit=${limit}`),

  pause: (c: Connection) => post<ControlResult>(c, '/api/control/pause'),
  resume: (c: Connection) => post<ControlResult>(c, '/api/control/resume'),
  kill: (c: Connection) => post<ControlResult>(c, '/api/control/kill'),
  revive: (c: Connection) => post<ControlResult>(c, '/api/control/revive'),
};

/** Probe a connection during setup, before it is saved. */
export async function verifyConnection(connection: Connection): Promise<Health> {
  await api.status(connection); // authenticated, so a bad token fails here
  return api.health(connection);
}
