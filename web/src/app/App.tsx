import {useCallback, useEffect, useRef, useState, type FormEvent} from 'react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {Theme} from '@astryxdesign/core/theme';
import {Button} from '@astryxdesign/core/Button';
import {Card} from '@astryxdesign/core/Card';
import {Heading} from '@astryxdesign/core/Heading';
import {IconButton} from '@astryxdesign/core/IconButton';
import {HStack, VStack} from '@astryxdesign/core/Stack';
import {Text} from '@astryxdesign/core/Text';
import {TextInput} from '@astryxdesign/core/TextInput';
import {AnimatedIcon} from '../components/icons/AnimatedIcon';
import {RefreshCWIcon} from '../components/icons/animated/refresh-cw';
import {SettingsIcon} from '../components/icons/animated/settings';
import {AppFrame} from '../components/patterns/AppFrame';
import {themes, defaultThemeSlug} from '../astryx-themes';
import {
  clearStoredToken, clearTokenFromHash, errorDescription, isLocalQueue, loadToken, readStoredToken, tokenFromHash,
  writeStoredToken, type TokenState,
} from '../features/decide/api';
import {DecidePage} from '../features/decide/DecidePage';
import {SettingsDialog, type Mode} from '../features/decide/SettingsDialog';
import {useNotifySetting} from '../features/decide/useNewDecisionNotice';

const MODE_KEY = 'dequ.mode';
// Use the saved choice when there is one, otherwise follow the device.
const initialMode = (): Mode => {
  try {
    const saved = localStorage.getItem(MODE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch { /* follow the device if storage cannot be read */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

const TOKEN_REJECTED = 'The server did not accept this token.';

function ConnectionProblem({message, onRetry}: {message: string; onRetry: () => void}) {
  return (
    <div className="page-content">
      <div className="decide-page">
        <Card padding={5}>
          <VStack gap={4}>
            <Heading level={1}>Connection problem</Heading>
            <div role="alert"><Text>{message}</Text></div>
            <Button label="Retry" variant="primary" onClick={onRetry} />
          </VStack>
        </Card>
      </div>
    </div>
  );
}

function TokenScreen({error, onConnect}: {error: string | null; onConnect: (token: string) => void}) {
  const [token, setToken] = useState('');
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = token.trim();
    if (next) onConnect(next);
  };
  return (
    <div className="page-content">
      <div className="decide-page">
        <Card padding={5}>
          <form onSubmit={submit}>
            <VStack gap={4}>
              <Heading level={1}>Connect</Heading>
              <Text>Enter the token for this DeQu server.</Text>
              {error ? <div role="alert"><Text>{error}</Text></div> : null}
              <TextInput label="Token" value={token} onChange={setToken} />
              <Button label="Connect" type="submit" variant="primary" isDisabled={!token.trim()} />
            </VStack>
          </form>
        </Card>
      </div>
    </div>
  );
}

export function App() {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {queries: {retry: false}, mutations: {retry: false}},
  }));
  const [session, setSession] = useState<TokenState>(loadToken);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  // Set only when the user submits a token, so a stored token's 401 does not show the rejection copy.
  const enteredToken = useRef<string | null>(null);
  // A token from the address bar is kept here after it leaves the URL, until the server says where it belongs.
  const fragmentToken = useRef<string | null>(null);
  useEffect(() => {
    if (session.status !== 'checking') return;
    let cancelled = false;
    const fromHash = tokenFromHash() ?? fragmentToken.current;
    fragmentToken.current = fromHash;
    clearTokenFromHash();
    const saved = readStoredToken();
    const preferred = fromHash ?? saved;
    void isLocalQueue().then(local => {
      if (cancelled) return;
      if (local) {
        // A local queue has nothing to protect, so an old token is obsolete rather than useful.
        fragmentToken.current = null;
        if (preferred !== null) {
          try { clearStoredToken(); } catch { /* the local session still opens */ }
        }
        setSession({status: 'local'});
        return;
      }
      if (preferred === null) {
        setSession({status: 'needs_token'});
        return;
      }
      if (fromHash !== null) {
        try { writeStoredToken(fromHash); } catch { /* keep the token for this visit */ }
      }
      fragmentToken.current = null;
      setSession({status: 'ready', token: preferred});
    }, error => {
      if (!cancelled) setSession({status: 'error', message: errorDescription(error)});
    });
    return () => { cancelled = true; };
  }, [session.status]);
  const [tokenNotice, setTokenNotice] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>(initialMode);
  const [isSettingsOpen, setSettingsOpen] = useState(false);
  const notify = useNotifySetting();
  const changeMode = (next: Mode) => {
    setMode(next);
    try { localStorage.setItem(MODE_KEY, next); } catch { /* the switch still applies for this visit */ }
  };
  const connect = useCallback((token: string) => {
    enteredToken.current = token;
    setTokenNotice(null);
    try { writeStoredToken(token); } catch { /* keep the token for this visit */ }
    queryClient.clear();
    setSession({status: 'ready', token});
  }, [queryClient]);
  const forget = useCallback(() => {
    enteredToken.current = null;
    setTokenNotice(null);
    try { clearStoredToken(); } catch { /* the screen still locks */ }
    queryClient.clear();
    setSettingsOpen(false);
    setSession({status: 'needs_token'});
  }, [queryClient]);
  const rejectToken = useCallback((failedToken: string | null) => {
    const current = sessionRef.current;
    if (current.status === 'local' && failedToken === null) {
      // The server now wants a token, for example after it gained one for a shared queue.
      queryClient.clear();
      setSettingsOpen(false);
      setSession({status: 'needs_token'});
      return;
    }
    // A 401 from a request made with a token that is no longer current must not clear the one in use.
    if (current.status !== 'ready' || current.token !== failedToken) return;
    const notice = enteredToken.current === failedToken ? TOKEN_REJECTED : null;
    enteredToken.current = null;
    setTokenNotice(notice);
    try { clearStoredToken(); } catch { /* the screen still locks */ }
    queryClient.clear();
    setSettingsOpen(false);
    setSession({status: 'needs_token'});
  }, [queryClient]);
  const token = session.status === 'ready' ? session.token : null;
  return (
    <QueryClientProvider client={queryClient}>
      <Theme theme={themes[defaultThemeSlug]} mode={mode}>
        {session.status === 'checking' ? (
          <div className="page-content"><div className="decide-page"><div role="status"><Text>Loading...</Text></div></div></div>
        ) : session.status === 'error' ? (
          <ConnectionProblem message={session.message} onRetry={() => setSession({status: 'checking'})} />
        ) : session.status === 'needs_token' ? <TokenScreen error={tokenNotice} onConnect={connect} /> : (
          <>
            <AppFrame appName="DeQu" navigation={[]}
              actions={
                <HStack gap={1} align="center">
                  {/* Reload is an action, not a setting, so it stays in the header. */}
                  <IconButton label="Reload" tooltip="Reload" variant="ghost" icon={<AnimatedIcon icon={RefreshCWIcon} />}
                    clickAction={async () => {
                      await Promise.all([
                        queryClient.invalidateQueries({queryKey: ['cards', token]}),
                        queryClient.invalidateQueries({queryKey: ['history', token]}),
                      ]);
                    }} />
                  <IconButton label="Settings" tooltip="Settings" variant="ghost" icon={<AnimatedIcon icon={SettingsIcon} />}
                    onClick={() => setSettingsOpen(true)} />
                </HStack>
              }>
              <div className="decide-page">
                {/* Key by token so drafts, later-order and in-flight answers from the previous token are dropped. */}
                <DecidePage key={token ?? 'local'} token={token} isNotifyEnabled={notify.isEnabled} onUnauthorized={rejectToken} />
              </div>
            </AppFrame>
            <SettingsDialog isOpen={isSettingsOpen} onOpenChange={setSettingsOpen}
              mode={mode} onModeChange={changeMode} notify={notify} hasToken={token !== null}
              onChangeToken={connect} onRemoveToken={forget} />
          </>
        )}
      </Theme>
    </QueryClientProvider>
  );
}
