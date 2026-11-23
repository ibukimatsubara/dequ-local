import {forwardRef, useImperativeHandle} from 'react';
import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, expect, test, vi} from 'vitest';
import {AnimatedIcon} from './AnimatedIcon';

const start = vi.fn();
const stop = vi.fn();
// Stand-in with the same handle as a lucide-animated component (startAnimation / stopAnimation).
const FakeIcon = forwardRef<{startAnimation: () => void; stopAnimation: () => void}, {size?: number}>((_props, ref) => {
  useImperativeHandle(ref, () => ({startAnimation: start, stopAnimation: stop}));
  return <svg data-testid="glyph" />;
});

beforeEach(() => { start.mockClear(); stop.mockClear(); });

test('inside a button, starts when the pointer enters the button and stops when it leaves', async () => {
  const user = userEvent.setup();
  render(<button type="button"><AnimatedIcon icon={FakeIcon} />Save</button>);
  await user.hover(screen.getByRole('button'));
  expect(start).toHaveBeenCalledTimes(1);
  await user.unhover(screen.getByRole('button'));
  expect(stop).toHaveBeenCalledTimes(1);
});

test('also starts when the button receives keyboard focus', async () => {
  const user = userEvent.setup();
  render(<button type="button"><AnimatedIcon icon={FakeIcon} />Save</button>);
  await user.tab();
  expect(start).toHaveBeenCalledTimes(1);
});

test('inside a data-animate-icons frame, starts when the pointer enters that frame', async () => {
  const user = userEvent.setup();
  render(<div data-animate-icons data-testid="row"><AnimatedIcon icon={FakeIcon} /><span>Notifications</span></div>);
  await user.hover(screen.getByText('Notifications'));
  expect(start).toHaveBeenCalledTimes(1);
});

test('does not animate when reduced motion is requested', async () => {
  const original = window.matchMedia;
  vi.stubGlobal('matchMedia', (query: string) => ({matches: query.includes('reduce'), addEventListener() {}, removeEventListener() {}}));
  const user = userEvent.setup();
  render(<button type="button"><AnimatedIcon icon={FakeIcon} />Save</button>);
  await user.hover(screen.getByRole('button'));
  expect(start).not.toHaveBeenCalled();
  vi.stubGlobal('matchMedia', original);
});
