import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {Badge} from '@astryxdesign/core/Badge';
import {Banner} from '@astryxdesign/core/Banner';
import {Button} from '@astryxdesign/core/Button';
import {Divider} from '@astryxdesign/core/Divider';
import {EmptyState} from '@astryxdesign/core/EmptyState';
import {Icon} from '@astryxdesign/core/Icon';
import {HStack, VStack} from '@astryxdesign/core/Stack';
import {Tab, TabList} from '@astryxdesign/core/TabList';
import {Text} from '@astryxdesign/core/Text';
import {
  ago, answerFailureMessages, ANSWER_COMMENT_LIMIT, commentLength, errorDescription, fetchCards, fetchHistory, isApiError, postAnswer,
  type Card,
} from './api';
import {DecisionCard, type CardHandle} from './DecisionCard';
import {useNewDecisionNotice} from './useNewDecisionNotice';

const TOO_LONG = 'An answer cannot be longer than 2,000 characters.';

function shortcutBlocked(event: KeyboardEvent): boolean {
  if (event.defaultPrevented) return true;
  const target = event.target;
  if (target instanceof Element && target.closest('input, textarea, select, [contenteditable="true"], dialog, [role="dialog"], [role="alertdialog"], [role="tablist"]')) {
    return true;
  }
  return [...document.querySelectorAll('dialog')].some(dialog => dialog.open);
}

export function DecidePage({token, isNotifyEnabled, onUnauthorized}: {
  token: string | null;
  isNotifyEnabled: boolean;
  onUnauthorized: (token: string | null) => void;
}) {
  const queryClient = useQueryClient();
  const cards = useQuery({queryKey: ['cards', token], queryFn: () => fetchCards(token), refetchInterval: 60_000});
  const [tab, setTab] = useState<'queue' | 'history'>('queue');
  const history = useQuery({
    queryKey: ['history', token],
    queryFn: () => fetchHistory(token),
    enabled: tab === 'history',
  });
  const [later, setLater] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [failures, setFailures] = useState<Record<string, string[]>>({});
  const holdDraft = useRef(false);
  // One in-flight answer per card. Set synchronously so a second click, swipe, key or Enter during the fly is ignored.
  const answeringRef = useRef<string | null>(null);
  const sentRef = useRef(false);
  const [answeringId, setAnsweringId] = useState<string | null>(null);
  const beginAnswer = useCallback((id: string) => {
    if (answeringRef.current !== null) return false;
    answeringRef.current = id;
    sentRef.current = false;
    setAnsweringId(id);
    return true;
  }, []);
  const endAnswer = useCallback((id: string) => {
    if (answeringRef.current !== id) return;
    answeringRef.current = null;
    sentRef.current = false;
    setAnsweringId(null);
  }, []);
  const answer = useMutation({
    mutationFn: (vars: {id: string; option: string | null; comment: string}) =>
      postAnswer(token, vars.id, {option: vars.option, comment: vars.comment}),
    onSuccess: (_data, vars) => {
      endAnswer(vars.id);
      setDrafts(current => {
        const {[vars.id]: _sent, ...rest} = current;
        return rest;
      });
      setFailures(current => {
        const {[vars.id]: _gone, ...rest} = current;
        return rest;
      });
      setLater(ids => ids.filter(id => id !== vars.id));
      queryClient.setQueryData<Card[]>(['cards', token], current => current?.filter(card => card.id !== vars.id));
      void queryClient.invalidateQueries({queryKey: ['cards', token]});
      void queryClient.invalidateQueries({queryKey: ['history', token]});
    },
    onError: (error, vars) => {
      endAnswer(vars.id);
      if (isApiError(error) && error.kind === 'unauthorized') return;
      const messages = isApiError(error) ? answerFailureMessages(error) : ['Could not save the answer.'];
      setFailures(current => ({...current, [vars.id]: messages.length > 0 ? messages : ['Could not save the answer.']}));
    },
  });
  const card = useRef<CardHandle>(null);

  useEffect(() => {
    if ([cards.error, history.error, answer.error].some(error => isApiError(error) && error.kind === 'unauthorized')) {
      onUnauthorized(token);
    }
  }, [cards.error, history.error, answer.error, onUnauthorized, token]);

  const all = cards.data ?? [];
  // Cards marked for later stay in that order at the end of the queue.
  const open = useMemo(() => {
    const waiting = all.filter(item => !later.includes(item.id));
    return [...waiting, ...later.flatMap(id => all.filter(item => item.id === id))];
  }, [all, later]);
  useNewDecisionNotice(cards.data ? open : undefined, isNotifyEnabled);
  const [top, next] = open;

  const sendAnswer = (item: Card, option: string | null, comment: string) => {
    if (answeringRef.current === item.id && sentRef.current) return;
    if (answeringRef.current !== null && answeringRef.current !== item.id) return;
    if (commentLength(comment) > ANSWER_COMMENT_LIMIT) {
      endAnswer(item.id);
      setFailures(current => ({...current, [item.id]: [TOO_LONG]}));
      return;
    }
    if (answeringRef.current !== item.id && !beginAnswer(item.id)) return;
    sentRef.current = true;
    setFailures(current => ({...current, [item.id]: []}));
    answer.mutate({id: item.id, option, comment});
    window.scrollTo({top: 0});
  };
  const sendLater = (item: Card) => {
    setLater(ids => [...ids.filter(id => id !== item.id), item.id]);
    window.scrollTo({top: 0});
  };
  const postpone = () => { if (top) card.current?.fly('left', () => sendLater(top)); };
  const recommend = () => {
    const option = top?.recommended;
    if (!top || !option) return;
    const comment = (drafts[top.id] ?? '').trim();
    if (commentLength(comment) > ANSWER_COMMENT_LIMIT) {
      setFailures(current => ({...current, [top.id]: [TOO_LONG]}));
      return;
    }
    if (!beginAnswer(top.id)) return;
    if (!card.current) {
      endAnswer(top.id);
      return;
    }
    card.current.fly('right', () => sendAnswer(top, option, comment));
  };

  useEffect(() => {
    if (tab !== 'queue' || !top) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
      if (shortcutBlocked(event)) return;
      if (event.key === 'ArrowRight') recommend();
      else postpone();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const loadError = cards.error && !(isApiError(cards.error) && cards.error.kind === 'unauthorized') ? cards.error : null;
  const historyError = history.error && !(isApiError(history.error) && history.error.kind === 'unauthorized') ? history.error : null;

  return (
    <VStack gap={4}>
      <TabList value={tab} onChange={value => setTab(value as 'queue' | 'history')} role="tablist" hasDivider layout="fill">
        <Tab value="queue" label="To decide" panelId="decide-queue" endContent={<Badge variant="neutral" label={String(open.length)} />} />
        <Tab value="history" label="History" panelId="decide-history" />
      </TabList>

      {loadError && <div role="alert"><Banner status="error" title="Could not load decisions"
        description={errorDescription(loadError)} endContent={<Button label="Retry" onClick={() => { void cards.refetch(); }} />} /></div>}

      {tab === 'queue' ? (
        <div id="decide-queue" role="tabpanel">
          {cards.isPending ? <div role="status"><Text>Loading...</Text></div>
            : top ? (
              <VStack gap={3}>
                {/* The next card sits behind this one so it shows as this card moves. */}
                <div className="decide-stack">
                  {next && (
                    <div className="decide-back" inert aria-hidden="true">
                      <DecisionCard key={`back-${next.id}`} card={next} draft="" messages={[]} isAnswering={false}
                        onDraftChange={() => undefined} onHoldDraft={() => undefined} onTooLong={() => undefined}
                        onBeginAnswer={() => false}
                        onAnswer={() => undefined} onLater={() => undefined} />
                    </div>
                  )}
                  <div className="decide-front">
                    <DecisionCard key={top.id} ref={card} card={top} draft={drafts[top.id] ?? ''}
                      messages={failures[top.id] ?? []}
                      isAnswering={answeringId === top.id}
                      onDraftChange={value => {
                        if (value === '' && holdDraft.current) {
                          holdDraft.current = false;
                          return;
                        }
                        if (answeringRef.current === top.id) return;
                        setDrafts(current => ({...current, [top.id]: value}));
                      }}
                      onHoldDraft={() => { holdDraft.current = true; }}
                      onTooLong={() => setFailures(current => ({...current, [top.id]: [TOO_LONG]}))}
                      onBeginAnswer={() => beginAnswer(top.id)}
                      onAnswer={(option, comment) => sendAnswer(top, option, comment)}
                      onLater={() => sendLater(top)} />
                  </div>
                </div>
              </VStack>
            ) : cards.isSuccess ? <EmptyState title="Nothing to decide" description="New decisions will show up here." /> : null}
        </div>
      ) : (
        <div id="decide-history" role="tabpanel">
          {historyError && <div role="alert"><Banner status="error" title="Could not load history"
            description={errorDescription(historyError)} endContent={<Button label="Retry" onClick={() => { void history.refetch(); }} />} /></div>}
          {history.isPending ? <div role="status"><Text>Loading...</Text></div>
            : history.isSuccess && history.data.length === 0 ? <EmptyState title="No history yet" description="Your answers and AI decisions will show up here." />
            : history.isSuccess ? (
              <VStack gap={3}>
                {history.data.map((entry, index) => (
                  <VStack key={entry.id} gap={1}>
                    {index > 0 && <Divider />}
                    <HStack gap={2} align="center" wrap="wrap">
                      {entry.by === 'ai'
                        ? <Badge variant="purple" label="AI decided" icon={<Icon icon="mivki:bot" />} />
                        : <Badge variant="blue" label="You decided" icon={<Icon icon="mivki:me" />} />}
                      <Text type="supporting">{`${entry.agent.name} · ${ago(entry.at)}`}</Text>
                    </HStack>
                    <Text type="supporting">{entry.question}</Text>
                    {entry.chose && <Text weight="semibold">{entry.chose}</Text>}
                    {entry.by === 'human' && entry.comment ? <Text type="supporting">{entry.comment}</Text> : null}
                    {entry.by === 'ai' && entry.why ? <Text type="supporting">{entry.why}</Text> : null}
                  </VStack>
                ))}
              </VStack>
            ) : null}
        </div>
      )}
    </VStack>
  );
}
