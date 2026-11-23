export type AgentKind = 'claude' | 'codex' | 'grok' | 'muse' | 'pi' | 'dsh' | 'other';
export type Agent = {kind: AgentKind; name: string; where: string};
export type Option = {id: string; label: string; effect: string};
export type Link = {kind: 'issue' | 'pr' | 'other'; label: string; url: string};
export type CanvasNode = {
  id: string;
  cx: number;
  top: number;
  name: string;
  role: string | null;
  icon: string | null;
};
export type CanvasGroup = {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  tone: 'neutral' | 'warm';
  icon: string | null;
};
export type CanvasEdge = {
  kind: 'h' | 'v';
  from: string;
  to: string;
  color: 'main' | 'sub' | 'fail';
  dashed: boolean;
  label: string | null;
  x: number | null;
  y: number | null;
};
export type CanvasSpec = {
  alt: string;
  panel: [number, number];
  groups: CanvasGroup[];
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  icons: Record<string, string>;
};
export type Card = {
  id: string;
  created_at: string;
  agent: Agent;
  task: string;
  progress: string;
  blocked: string;
  question: string;
  options: Option[];
  recommended: string | null;
  reason: string | null;
  links: Link[];
  canvas: CanvasSpec | null;
  details: string | null;
  due: string | null;
};
export type HistoryEntry = {
  id: string;
  by: 'human' | 'ai';
  agent: Agent;
  question: string;
  chose: string | null;
  comment: string;
  why: string | null;
  at: string;
};
export type ApiError =
  | {kind: 'unauthorized'}
  | {kind: 'invalid'; messages: string[]}
  | {kind: 'not_found'}
  | {kind: 'conflict'}
  | {kind: 'failed'; message: string};

export const TOKEN_KEY = 'dequ.token';
export const ANSWER_COMMENT_LIMIT = 2000;

// Code points, not UTF-16 units, so this matches the server's str max_length.
export function commentLength(text: string): number {
  return [...text].length;
}

export type TokenState =
  | {status: 'checking'}
  | {status: 'error'; message: string}
  | {status: 'needs_token'}
  | {status: 'ready'; token: string}
  | {status: 'local'};

export function isApiError(error: unknown): error is ApiError {
  if (typeof error !== 'object' || error === null || !('kind' in error)) return false;
  const kind = (error as {kind: unknown}).kind;
  return kind === 'unauthorized' || kind === 'invalid' || kind === 'not_found' || kind === 'conflict' || kind === 'failed';
}

export function answerFailureMessages(error: ApiError): string[] {
  switch (error.kind) {
    case 'invalid':
      return error.messages.length > 0 ? error.messages : ['The answer was rejected.'];
    case 'not_found':
      return ['This card was withdrawn or has expired.'];
    case 'conflict':
      return ['This card was already answered.'];
    case 'failed':
      return [error.message];
    case 'unauthorized':
      return [];
  }
}

export function errorDescription(error: unknown): string {
  if (isApiError(error)) {
    if (error.kind === 'failed') return error.message;
    if (error.kind === 'invalid') return error.messages.join(' ') || 'The request was rejected.';
    if (error.kind === 'not_found') return 'Not found.';
    if (error.kind === 'conflict') return 'Conflict.';
    return 'Unauthorized.';
  }
  if (error instanceof Error && error.message) return error.message;
  return 'Something went wrong.';
}

export function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function writeStoredToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// Read the token without removing it yet, so a retry or a second effect run can still use it.
export function tokenFromHash(): string | null {
  const hash = window.location.hash;
  if (!hash.startsWith('#')) return null;
  const params = new URLSearchParams(hash.slice(1));
  return params.get('token') || null;
}

// Remove the credential from the address bar and preserve other fragment parameters.
export function clearTokenFromHash(): void {
  const hash = window.location.hash;
  if (!hash.startsWith('#')) return;
  const params = new URLSearchParams(hash.slice(1));
  if (!params.has('token')) return;
  params.delete('token');
  const rest = params.toString();
  history.replaceState(null, '', `${window.location.pathname}${window.location.search}${rest ? `#${rest}` : ''}`);
}

export function loadToken(): TokenState {
  // A queue can be local and need no token, so ask the server before showing the token screen.
  return {status: 'checking'};
}

/** The local server names its credential-free mode in the public health response. */
export async function isLocalQueue(): Promise<boolean> {
  let response: Response;
  try {
    response = await fetch('/api/health', {headers: {Accept: 'application/json'}});
  } catch (error) {
    throw {kind: 'failed', message: error instanceof Error ? error.message : 'Could not reach the server.'} satisfies ApiError;
  }
  if (!response.ok) throw await errorFrom(response);
  let body: {ok?: unknown; auth?: unknown} | null;
  try {
    body = await response.json() as {ok?: unknown; auth?: unknown} | null;
  } catch {
    throw {kind: 'failed', message: 'The server returned an unexpected health response.'} satisfies ApiError;
  }
  if (body?.ok !== true) throw {kind: 'failed', message: 'The server returned an unexpected health response.'} satisfies ApiError;
  return body.auth === 'local';
}

async function request(token: string | null, path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? {'Content-Type': 'application/json'} : {}),
        ...(token === null ? {} : {Authorization: `Bearer ${token}`}),
      },
    });
  } catch (error) {
    throw {kind: 'failed', message: error instanceof Error ? error.message : 'Could not reach the server.'} satisfies ApiError;
  }
  if (response.status === 401) throw {kind: 'unauthorized'} satisfies ApiError;
  return response;
}

async function errorFrom(response: Response): Promise<ApiError> {
  if (response.status === 401) return {kind: 'unauthorized'};
  if (response.status === 404) return {kind: 'not_found'};
  if (response.status === 409) return {kind: 'conflict'};
  if (response.status === 422) {
    let messages: string[] = [];
    try {
      const body = await response.json() as {errors?: {msg?: unknown}[]};
      messages = (body.errors ?? []).flatMap(error => typeof error.msg === 'string' ? [error.msg] : []);
    } catch { /* keep the empty list and use the fallback text */ }
    return {kind: 'invalid', messages};
  }
  let message = `Request failed (${response.status})`;
  try {
    const body = await response.json() as {error?: unknown};
    if (typeof body.error === 'string' && body.error) message = body.error;
  } catch { /* keep the status text */ }
  return {kind: 'failed', message};
}

export async function fetchCards(token: string | null): Promise<Card[]> {
  const response = await request(token, '/api/cards');
  if (!response.ok) throw await errorFrom(response);
  const body = await response.json() as {cards?: Card[]};
  if (!Array.isArray(body.cards)) throw {kind: 'failed', message: 'The server returned an unexpected cards response.'} satisfies ApiError;
  return body.cards;
}

export async function fetchHistory(token: string | null): Promise<HistoryEntry[]> {
  const response = await request(token, '/api/history');
  if (!response.ok) throw await errorFrom(response);
  const body = await response.json() as {entries?: HistoryEntry[]};
  if (!Array.isArray(body.entries)) throw {kind: 'failed', message: 'The server returned an unexpected history response.'} satisfies ApiError;
  return body.entries;
}

export async function postAnswer(token: string | null, id: string, body: {option: string | null; comment: string}): Promise<void> {
  const response = await request(token, `/api/cards/${encodeURIComponent(id)}/answer`, {
    method: 'POST',
    // The page defaults to no-referrer, but the server's same-origin check needs this Origin header.
    referrerPolicy: 'same-origin',
    body: JSON.stringify(body),
  });
  if (response.status === 204) return;
  throw await errorFrom(response);
}

// Due is inclusive through the end of that calendar day.
export function daysLeft(due: string | null, now = new Date()): number | null {
  if (!due) return null;
  return Math.ceil((new Date(`${due}T23:59:59`).getTime() - now.getTime()) / 86_400_000);
}

export function ago(at: string, now = new Date()): string {
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(at).getTime()) / 60_000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}
