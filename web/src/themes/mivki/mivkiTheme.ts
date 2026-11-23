import {defineTheme} from '@astryxdesign/core/theme';
import {neutralTheme} from '@astryxdesign/theme-neutral/built';
import {mivkiIcons} from './mivkiIcons';

// Brand changes live in this definition; the screen uses the built theme.
export const mivkiTheme = defineTheme({
  name: 'mivki',
  extends: neutralTheme,
  icons: mivkiIcons,
  // System stack: the server Content-Security-Policy blocks third-party font hosts.
  typography: {
    body: {
      family: '-apple-system',
      fallbacks: 'BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    },
    heading: {
      family: '-apple-system',
      fallbacks: 'BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    },
  },
  // Align the top bar with the content column (560px, 16px side inset on phones).
  components: {
    'top-nav': {base: {paddingInline: 'max(var(--spacing-4), calc((100% - 560px) / 2))'}},
  },
});
