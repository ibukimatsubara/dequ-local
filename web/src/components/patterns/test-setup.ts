import {afterEach, vi} from 'vitest';
import {cleanup} from '@testing-library/react';

afterEach(cleanup);

// Fill only the browser APIs jsdom does not have. Components and async behavior stay real.
vi.stubGlobal('matchMedia', (media: string) => Object.assign(new EventTarget(), {
  matches: false, media, onchange: null, addListener() {}, removeListener() {},
}));

HTMLDialogElement.prototype.showModal = function () {this.open = true;};
HTMLDialogElement.prototype.close = function () {
  this.open = false;
  this.dispatchEvent(new Event('close'));
};
