import react from '@vitejs/plugin-react';
import {defineConfig} from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  // During development, send /api to the local DeQu server with the browser's Host and address, so the local
  // credential-free server still sees this computer while a shared dev proxy keeps remote clients remote.
  server: {
    proxy: {
      '/api': {target: 'http://127.0.0.1:8790', changeOrigin: false, xfwd: true},
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/components/patterns/test-setup.ts'],
  },
});
