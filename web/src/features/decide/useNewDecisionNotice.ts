import {useEffect, useRef, useState} from 'react';
import type {Card} from './api';

const STORAGE_KEY = 'dequ.notify';
const canNotify = () => typeof window !== 'undefined' && window.isSecureContext && 'Notification' in window;
const readEnabled = () => {
  try { return localStorage.getItem(STORAGE_KEY) === 'on'; } catch { return false; }
};

async function show(title: string, body: string) {
  // Mobile Chrome only delivers notifications that come from a service worker.
  const registration = await navigator.serviceWorker?.getRegistration();
  if (registration) await registration.showNotification(title, {body, tag: 'dequ-new'});
  else new Notification(title, {body, tag: 'dequ-new'});
}

/** On/off for notifications. Permission is asked of the browser; the choice is stored on the device. */
export function useNotifySetting() {
  const [enabled, setEnabled] = useState(() => canNotify() && Notification.permission === 'granted' && readEnabled());

  useEffect(() => {
    if (canNotify() && 'serviceWorker' in navigator) void navigator.serviceWorker.register('./sw.js').catch(() => undefined);
  }, []);

  const toggle = async () => {
    if (enabled) {
      setEnabled(false);
      try { localStorage.setItem(STORAGE_KEY, 'off'); } catch { /* keep going if storage is blocked */ }
      return;
    }
    if ((await Notification.requestPermission()) !== 'granted') return;
    setEnabled(true);
    try { localStorage.setItem(STORAGE_KEY, 'on'); } catch { /* keep going if storage is blocked */ }
    void show('Notifications are on', 'New decisions will show up here.').catch(() => undefined);
  };

  const blocked = canNotify() && Notification.permission === 'denied';
  return {isAvailable: canNotify(), isEnabled: enabled, isBlocked: blocked, toggle};
}
export type NotifySetting = ReturnType<typeof useNotifySetting>;

/**
 * Notify when a new decision arrives, and put the count in the tab title.
 * Notifications are delivered only while this page is open, including in another tab or when minimized.
 */
export function useNewDecisionNotice(open: readonly Card[] | undefined, enabled: boolean) {
  const seen = useRef<Set<string> | null>(null);

  useEffect(() => {
    if (!open) return;
    document.title = open.length ? `(${open.length}) DeQu` : 'DeQu';
    const ids = new Set(open.map(item => item.id));
    const added = seen.current ? open.filter(item => !seen.current?.has(item.id)) : [];
    seen.current = ids;
    if (enabled && added.length) {
      void show(`${open.length} to decide`, added.map(item => item.question).join('\n')).catch(() => undefined);
    }
  }, [open, enabled]);
}
