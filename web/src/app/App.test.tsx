import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';
import type {Card, HistoryEntry} from '../features/decide/api';
import {App} from './App';

const TOKEN = 'secret-token';

const card = (overrides: Partial<Card> = {}): Card => ({
  id: 'card-1',
  created_at: new Date().toISOString(),
  agent: {kind: 'dsh', name: 'dsh', where: 'laptop'},
  task: 'Add Google sign-in to the login page.',
  progress: 'The button and the callback work with a test account.',
  blocked: 'The consent screen needs an app name before production.',
  question: 'Which name goes on the consent screen?',
  options: [
    {id: 'product', label: 'Product name', effect: 'Clear to users. Renaming the product means another review.'},
    {id: 'company', label: 'Company name', effect: 'Reusable across products. Less clear to users.'},
  ],
  recommended: 'product',
  reason: 'People see what they are granting access to.',
  links: [{kind: 'pr', label: 'PR #57', url: 'https://github.com/acme/shop/pull/57'}],
  canvas: null,
  details: null,
  due: null,
  ...overrides,
});

type Call = {method: string; path: string; auth: string | null; body: unknown};
type Reply = {status: number; body?: unknown};

class FakeServer {
  calls: Call[] = [];
  cards: Card[] = [card()];
  history: HistoryEntry[] = [];
  requiresToken = true;
  validToken = TOKEN;
  answerReply: Reply | null = null;

  handle = async (input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input), 'http://dequ.test');
    const headers = new Headers(init.headers);
    const method = init.method ?? 'GET';
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined;
    this.calls.push({method, path: url.pathname, auth: headers.get('Authorization'), body});
    const json = (status: number, payload?: unknown) =>
      new Response(payload === undefined ? null : JSON.stringify(payload), {status, headers: {'Content-Type': 'application/json'}});
    if (method === 'GET' && url.pathname === '/api/health') {
      return json(200, this.requiresToken ? {ok: true} : {ok: true, auth: 'local'});
    }
    if (this.requiresToken && headers.get('Authorization') !== `Bearer ${this.validToken}`) return json(401, {error: 'unauthorized'});
    if (method === 'GET' && url.pathname === '/api/cards') return json(200, {cards: this.cards});
    if (method === 'GET' && url.pathname === '/api/history') return json(200, {entries: this.history});
    const answer = url.pathname.match(/^\/api\/cards\/([^/]+)\/answer$/);
    if (method === 'POST' && answer) {
      if (this.answerReply) return json(this.answerReply.status, this.answerReply.body);
      this.cards = this.cards.filter(item => item.id !== answer[1]);
      return new Response(null, {status: 204});
    }
    return json(404, {error: 'not found'});
  };

  answers() { return this.calls.filter(call => call.method === 'POST'); }
}

let server: FakeServer;

beforeEach(() => {
  server = new FakeServer();
  vi.stubGlobal('fetch', vi.fn(server.handle));
  vi.stubGlobal('matchMedia', (media: string) => Object.assign(new EventTarget(), {
    matches: media.includes('reduce'), media, onchange: null, addListener() {}, removeListener() {},
  }));
  localStorage.clear();
  history.replaceState(null, '', '/');
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.stubGlobal('matchMedia', (media: string) => Object.assign(new EventTarget(), {
    matches: false, media, onchange: null, addListener() {}, removeListener() {},
  }));
});

const signIn = () => localStorage.setItem('dequ.token', TOKEN);

const question = 'Which name goes on the consent screen?';

test('a saved token on a local queue opens it locally and is removed', async () => {
  server.requiresToken = false;
  signIn();
  render(<App />);
  expect(await screen.findByRole('heading', {name: question})).toBeTruthy();
  expect(localStorage.getItem('dequ.token')).toBeNull();
  expect(screen.queryByLabelText('Token')).toBeNull();
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', {name: 'Settings'}));
  expect(await screen.findByRole('heading', {name: 'Settings'})).toBeTruthy();
  expect(screen.queryByRole('button', {name: 'Remove token'})).toBeNull();
});

test('a token in the address bar for a local queue is dropped and not saved', async () => {
  server.requiresToken = false;
  history.replaceState(null, '', `/#token=${TOKEN}`);
  render(<App />);
  expect(await screen.findByRole('heading', {name: question})).toBeTruthy();
  expect(localStorage.getItem('dequ.token')).toBeNull();
  expect(window.location.hash).toBe('');
  expect(screen.queryByLabelText('Token')).toBeNull();
});

test('removes a shared token from the URL before retrying a failed first connection', async () => {
  history.replaceState(null, '', `/#token=${TOKEN}`);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, {status: 503})));
  render(<App />);
  expect(await screen.findByRole('button', {name: 'Retry'})).toBeTruthy();
  expect(window.location.hash).toBe('');
  expect(localStorage.getItem('dequ.token')).toBeNull();
  vi.stubGlobal('fetch', vi.fn(server.handle));
  await userEvent.setup().click(screen.getByRole('button', {name: 'Retry'}));
  expect(await screen.findByRole('heading', {name: question})).toBeTruthy();
  expect(localStorage.getItem('dequ.token')).toBe(TOKEN);
});

test('a server error on first open can be retried without asking for a token', async () => {
  server.requiresToken = false;
  let reachable = false;
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    reachable ? server.handle(input, init) : Promise.resolve(new Response(null, {status: 503}))));
  render(<App />);
  expect(await screen.findByText('Request failed (503)')).toBeTruthy();
  expect(screen.queryByLabelText('Token')).toBeNull();
  reachable = true;
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', {name: 'Retry'}));
  expect(await screen.findByRole('button', {name: 'Choose Product name'})).toBeTruthy();
});

const enterToken = async (value: string) => {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText('Token'), value);
  await user.click(screen.getByRole('button', {name: 'Connect'}));
};

test('opens a local queue and sends an answer without a token', async () => {
  server.requiresToken = false;
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', {name: 'Choose Product name'}));
  await waitFor(() => expect(server.answers()).toHaveLength(1));
  expect(server.answers()[0].auth).toBeNull();
  expect(screen.queryByLabelText('Token')).toBeNull();
});

test('an unhealthy server does not ask for a token', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => Response.json({ok: false})));
  render(<App />);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  const message = await screen.findByText('The server returned an unexpected health response.');
  expect(message.closest('[role="alert"]')).toBeTruthy();
  expect(screen.queryByLabelText('Token')).toBeNull();
});

test('without a saved token, asks for one, saves it and loads cards with it', async () => {
  render(<App />);
  await enterToken(TOKEN);
  expect(await screen.findByRole('heading', {name: 'Which name goes on the consent screen?'})).toBeTruthy();
  expect(localStorage.getItem('dequ.token')).toBe(TOKEN);
  expect(server.calls.find(call => call.path === '/api/cards')?.auth).toBe(`Bearer ${TOKEN}`);
});

test('takes the token from #token= and removes it from the address bar', async () => {
  history.replaceState(null, '', `/#token=${TOKEN}`);
  render(<App />);
  expect(await screen.findByRole('heading', {name: 'Which name goes on the consent screen?'})).toBeTruthy();
  expect(localStorage.getItem('dequ.token')).toBe(TOKEN);
  expect(window.location.hash).toBe('');
});

test('a wrong token goes back to the token screen', async () => {
  localStorage.setItem('dequ.token', 'wrong');
  render(<App />);
  expect(await screen.findByLabelText('Token')).toBeTruthy();
  expect(screen.queryByRole('heading', {name: 'Which name goes on the consent screen?'})).toBeNull();
});

test('choosing an option sends it and removes the card only after it was saved', async () => {
  signIn();
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', {name: 'Choose Product name'}));
  await waitFor(() => expect(server.answers()).toHaveLength(1));
  expect(server.answers()[0]).toMatchObject({path: '/api/cards/card-1/answer', auth: `Bearer ${TOKEN}`, body: {option: 'product', comment: ''}});
  expect(await screen.findByText('Nothing to decide')).toBeTruthy();
});

test.each([
  [{status: 422, body: {errors: [{loc: ['option'], msg: 'option is not one of the card\'s option ids'}]}}, 'option is not one of the card\'s option ids'],
  [{status: 404, body: {error: 'card not found'}}, 'This card was withdrawn or has expired.'],
  [{status: 409, body: {error: 'card is already answered'}}, 'This card was already answered.'],
])('when saving fails (%o), keeps the card and the draft and says why', async (reply, message) => {
  signIn();
  server.answerReply = reply;
  render(<App />);
  const user = userEvent.setup();
  const input = await screen.findByPlaceholderText(/Answer in your own words/);
  await user.type(input, 'Use the product name, but ask legal first');
  await user.click(screen.getByRole('button', {name: 'Send'}));
  expect(await screen.findByText(message)).toBeTruthy();
  expect(screen.getByRole('heading', {name: 'Which name goes on the consent screen?'})).toBeTruthy();
  expect((screen.getByPlaceholderText(/Answer in your own words/) as HTMLTextAreaElement).value)
    .toBe('Use the product name, but ask legal first');
});

test('warns instead of sending a written answer over 2,000 characters', async () => {
  signIn();
  render(<App />);
  const input = await screen.findByPlaceholderText(/Answer in your own words/);
  const user = userEvent.setup();
  await user.click(input);
  await user.paste('a'.repeat(2001));
  await user.click(screen.getByRole('button', {name: 'Send'}));
  expect(await screen.findByText(/2,000 characters/)).toBeTruthy();
  expect(server.answers()).toHaveLength(0);
});

test('the history tab shows what you and the AI decided from the server', async () => {
  signIn();
  server.history = [
    {id: 'h1', by: 'human', agent: {kind: 'claude', name: 'Claude Code', where: 'laptop'}, question: 'Which database?',
      chose: 'SQLite', comment: 'keep it simple', why: null, at: new Date().toISOString()},
    {id: 'h2', by: 'ai', agent: {kind: 'codex', name: 'Codex', where: 'server'}, question: 'Which test runner?',
      chose: 'pytest', comment: '', why: 'Already used in the repo.', at: new Date().toISOString()},
  ];
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('tab', {name: 'History'}));
  const panel = await screen.findByRole('tabpanel');
  expect(await within(panel).findByText('Which database?')).toBeTruthy();
  expect(within(panel).getByText('You decided')).toBeTruthy();
  expect(within(panel).getByText('AI decided')).toBeTruthy();
  expect(within(panel).getByText('Already used in the repo.')).toBeTruthy();
  expect(server.calls.find(call => call.path === '/api/history')?.auth).toBe(`Bearer ${TOKEN}`);
});

test('shows the host name next to each link label', async () => {
  signIn();
  server.cards = [card({links: [{kind: 'other', label: 'Design doc', url: 'https://evil.example.com/doc'}]})];
  render(<App />);
  const link = await screen.findByRole('link', {name: /Design doc/});
  expect(link.closest('div')?.textContent).toContain('evil.example.com');
});

test('does not load images inside the details', async () => {
  signIn();
  server.cards = [card({details: 'Before\n\n![tracking pixel](https://evil.example.com/pixel.png)\n\nAfter'})];
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', {name: 'Details'}));
  expect(await screen.findByText('After')).toBeTruthy();
  expect(document.querySelector('img[src*="evil.example.com"]')).toBeNull();
  expect(screen.getByText(/tracking pixel/)).toBeTruthy();
});

test('removing the token in settings goes back to the token screen', async () => {
  signIn();
  render(<App />);
  const user = userEvent.setup();
  await screen.findByRole('heading', {name: 'Which name goes on the consent screen?'});
  await user.click(screen.getByRole('button', {name: 'Settings'}));
  await user.click(await screen.findByRole('button', {name: 'Remove token'}));
  expect(await screen.findByLabelText('Token')).toBeTruthy();
  expect(localStorage.getItem('dequ.token')).toBeNull();
});

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

test('says why when the token was rejected', async () => {
  render(<App />);
  await enterToken('wrong-token');
  expect(await screen.findByText('The server did not accept this token.')).toBeTruthy();
});

test('confirming a Japanese IME conversion with Enter does not send the answer', async () => {
  signIn();
  render(<App />);
  const input = await screen.findByPlaceholderText(/Answer in your own words/);
  fireEvent.change(input, {target: {value: 'still typing'}});
  fireEvent.keyDown(input, {key: 'Enter', keyCode: 229, isComposing: true});
  await sleep(300);
  expect(server.answers()).toHaveLength(0);
});

test('arrow keys do not answer the card while the details are open', async () => {
  signIn();
  server.cards = [card({details: 'Long background'})];
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', {name: 'Details'}));
  await screen.findByText('Long background');
  fireEvent.keyDown(document.activeElement ?? document.body, {key: 'ArrowRight'});
  await sleep(300);
  expect(server.answers()).toHaveLength(0);
});

test('a swipe cancelled by the browser does not answer the card', async () => {
  signIn();
  render(<App />);
  const heading = await screen.findByRole('heading', {name: question});
  HTMLElement.prototype.setPointerCapture ??= () => undefined;
  fireEvent.pointerDown(heading, {pointerId: 1, clientX: 100, clientY: 100});
  fireEvent.pointerMove(heading, {pointerId: 1, clientX: 210, clientY: 100});
  fireEvent.pointerCancel(heading, {pointerId: 1, clientX: 210, clientY: 100});
  await sleep(300);
  expect(server.answers()).toHaveLength(0);
});

test('counts the 2,000 characters the way the server does (emoji count once)', async () => {
  signIn();
  render(<App />);
  const input = await screen.findByPlaceholderText(/Answer in your own words/);
  const user = userEvent.setup();
  await user.click(input);
  await user.paste('\u{1F600}'.repeat(1100));
  await user.click(screen.getByRole('button', {name: 'Send'}));
  await waitFor(() => expect(server.answers()).toHaveLength(1));
});

test('Reload on the history tab reads the history again', async () => {
  signIn();
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('tab', {name: 'History'}));
  await screen.findByRole('tabpanel');
  server.history = [{id: 'h9', by: 'ai', agent: {kind: 'codex', name: 'Codex', where: 'server'}, question: 'Which linter?',
    chose: 'ruff', comment: '', why: 'Fast.', at: new Date().toISOString()}];
  await user.click(screen.getByRole('button', {name: 'Reload'}));
  expect(await screen.findByText('Which linter?')).toBeTruthy();
});

test.each(['lucide/user', 'constructor'])('diagram logo %s falls back to an initial', async (icon) => {
  signIn();
  server.cards = [card({canvas: {
    alt: 'User signs in with Google.', panel: [320, 300], groups: [], edges: [],
    nodes: [
      {id: 'user', cx: 160, top: 20, name: 'User', role: null, icon},
      {id: 'pay', cx: 160, top: 160, name: 'Pay', role: null, icon: 'pay'},
    ],
    icons: {'lucide/user': '/api/icons/lucide/user', pay: 'data:image/svg+xml;base64,PHN2Zy8+'},
  }})];
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', {name: 'Diagram'}));
  await waitFor(() => expect(document.querySelector('svg image[href^="data:"]')).toBeTruthy());
  expect(document.querySelector('svg text[aria-hidden="true"]')?.textContent).toBe('U');
  expect(document.querySelector('svg image[href^="/api/icons"]')).toBeNull();
});

const sources = import.meta.glob(['/src/**/*.{ts,tsx,css,mjs,json}', '/index.html', '/vite.config.ts', '/scripts/*'],
  {query: '?raw', import: 'default', eager: true}) as Record<string, string>;
const publicFiles = Object.keys(import.meta.glob('/public/*', {query: '?url', eager: true}));
// The <head> lines from brand/export/head-snippet.html.
const headSnippet = [
  '<link rel="icon" href="/favicon.ico" sizes="48x48">',
  '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
  '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
  '<link rel="manifest" href="/site.webmanifest">',
  '<meta name="theme-color" content="#111111">',
];

test('the app has no Japanese text left', () => {
  const japanese = /[\u3040-\u30ff\u3400-\u9fff\uff00-\uffef]/;
  expect(Object.entries(sources).filter(([, text]) => japanese.test(text)).map(([path]) => path)).toEqual([]);
});

test('index.html loads no third-party fonts and links the DeQu icons', () => {
  const html = sources['/index.html'];
  expect(html).not.toContain('fonts.googleapis.com');
  expect(html).toContain('<html lang="en">');
  for (const line of headSnippet) expect(html).toContain(line);
  for (const file of ['favicon.ico', 'favicon.svg', 'apple-touch-icon.png', 'icon-192.png', 'icon-512.png', 'maskable-512.png', 'site.webmanifest']) {
    expect(publicFiles).toContain(`/public/${file}`);
  }
});

test('the sample data is gone from the app', () => {
  expect(Object.keys(sources).filter(path => /sample/i.test(path))).toEqual([]);
});
