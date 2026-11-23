import {act, renderHook} from '@testing-library/react';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';
import type {Card} from './api';
import {useNewDecisionNotice, useNotifySetting} from './useNewDecisionNotice';

// Same wiring as the screen: read the on/off setting, then pass it to the notice hook.
const useNotice = (open: readonly Card[] | undefined) => {
  const setting = useNotifySetting();
  useNewDecisionNotice(open, setting.isEnabled);
  return setting;
};

const item = (id: string, question: string): Card => ({
  id, created_at: '2026-01-01T00:00:00Z',
  agent: {kind: 'claude', name: 'Claude Code', where: 'PC'},
  task: 'Task', progress: 'Progress', blocked: 'Blocked', question,
  options: [{id: 'x', label: 'X', effect: 'x'}, {id: 'y', label: 'Y', effect: 'y'}],
  recommended: null, reason: null, links: [], canvas: null, details: null, due: null,
});

const created: {title: string; body?: string}[] = [];
class FakeNotification {
  static permission: NotificationPermission = 'granted';
  static requestPermission = vi.fn(async () => FakeNotification.permission);
  constructor(title: string, options?: NotificationOptions) { created.push({title, body: options?.body}); }
}

beforeEach(() => {
  created.length = 0;
  FakeNotification.permission = 'granted';
  vi.stubGlobal('Notification', FakeNotification);
  vi.stubGlobal('isSecureContext', true);
  localStorage.setItem('dequ.notify', 'on');
  document.title = '';
});
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

test('does not notify for the first load, only for decisions that arrive later', async () => {
  const first = [item('a', 'Already waiting')];
  const {rerender} = renderHook(({open}) => useNotice(open), {initialProps: {open: first as Card[] | undefined}});
  await flush();
  expect(created).toEqual([]);
  expect(document.title).toBe('(1) DeQu');

  rerender({open: [...first, item('b', 'A new decision')]});
  await flush();
  expect(created).toEqual([{title: '2 to decide', body: 'A new decision'}]);
  expect(document.title).toBe('(2) DeQu');
});

test('does not notify when the count only drops or the same items are fetched again', async () => {
  const both = [item('a', 'A'), item('b', 'B')];
  const {rerender} = renderHook(({open}) => useNotice(open), {initialProps: {open: both as Card[] | undefined}});
  rerender({open: [...both]});
  rerender({open: [both[0]!]});
  rerender({open: []});
  await flush();
  expect(created).toEqual([]);
  expect(document.title).toBe('DeQu');
});

test('does not notify when notifications are off', async () => {
  localStorage.setItem('dequ.notify', 'off');
  const {result, rerender} = renderHook(({open}) => useNotice(open), {initialProps: {open: [] as Card[] | undefined}});
  expect(result.current.isEnabled).toBe(false);
  rerender({open: [item('a', 'A')]});
  await flush();
  expect(created).toEqual([]);
});

test('turning notifications on asks for permission and enables them when granted', async () => {
  localStorage.setItem('dequ.notify', 'off');
  const {result} = renderHook(() => useNotice([]));
  await act(async () => { await result.current.toggle(); });
  expect(FakeNotification.requestPermission).toHaveBeenCalled();
  expect(result.current.isEnabled).toBe(true);
  expect(localStorage.getItem('dequ.notify')).toBe('on');
});

test('is unavailable when the page is not a secure context', () => {
  vi.stubGlobal('isSecureContext', false);
  const {result} = renderHook(() => useNotice([]));
  expect(result.current.isAvailable).toBe(false);
});
