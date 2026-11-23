import {useImperativeHandle, useRef, useState, type PointerEvent, type ReactNode, type Ref} from 'react';
import {Badge} from '@astryxdesign/core/Badge';
import {BottomSheet} from '@astryxdesign/core/BottomSheet';
import {Button} from '@astryxdesign/core/Button';
import {Card} from '@astryxdesign/core/Card';
import {ClickableCard} from '@astryxdesign/core/ClickableCard';
import {Heading} from '@astryxdesign/core/Heading';
import {Icon} from '@astryxdesign/core/Icon';
import {IconButton} from '@astryxdesign/core/IconButton';
import {Link} from '@astryxdesign/core/Link';
import {Markdown} from '@astryxdesign/core/Markdown';
import {ChatComposer} from '@astryxdesign/core/Chat';
import {HStack, VStack} from '@astryxdesign/core/Stack';
import {Text} from '@astryxdesign/core/Text';
import {ago, daysLeft, commentLength, ANSWER_COMMENT_LIMIT, type Card as Decision, type Link as CardLink} from './api';
import {Canvas} from './Canvas';
import {AnimatedIcon} from '../../components/icons/AnimatedIcon';
import {ArrowLeftIcon} from '../../components/icons/animated/arrow-left';

const linkIcon: Record<CardLink['kind'], ReactNode> = {
  pr: <Icon icon="mivki:pr" size="sm" color="secondary" />,
  issue: <Icon icon="mivki:issue" size="sm" color="secondary" />,
  other: <Icon icon="mivki:doc" size="sm" color="secondary" />,
};
type Panel = 'canvas' | 'details';
const SWIPE_DISTANCE = 100;
const FLY_MS = 220;
const COMPOSER_PLACEHOLDER = 'Answer in your own words (none of these, or add a condition)';

export type CardHandle = {fly: (direction: 'left' | 'right', then: () => void) => void};

function linkHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return '';
  }
}

function MarkdownImage({alt, src}: {alt: string; src: string}) {
  if (alt.trim()) return <span>{alt}</span>;
  return <a href={src}>{src}</a>;
}

export function DueBadge({due}: {due: string | null}) {
  const days = daysLeft(due);
  if (days === null || !due) return null;
  const date = due.slice(5).replace('-', '/');
  if (days < 0) return <Badge variant="error" label={`${date} overdue`} />;
  if (days <= 3) return <Badge variant="warning" label={`${date} ${days}d left`} />;
  return <Text type="supporting">{`Due ${date} (${days}d left)`}</Text>;
}

type Props = {
  card: Decision;
  draft: string;
  messages: string[];
  isAnswering: boolean;
  onDraftChange: (value: string) => void;
  onHoldDraft: () => void;
  onTooLong: () => void;
  onBeginAnswer: () => boolean;
  onAnswer: (option: string | null, comment: string) => void;
  onLater: () => void;
  ref?: Ref<CardHandle>;
};

export function DecisionCard({card, draft, messages, isAnswering, onDraftChange, onHoldDraft, onTooLong, onBeginAnswer, onAnswer, onLater, ref}: Props) {
  const swipe = useRef<CardHandle>(null);
  useImperativeHandle(ref, () => ({fly: (direction, then) => swipe.current?.fly(direction, then)}));
  const recommended = card.options.find(option => option.id === card.recommended);
  // The diagram and the long write-up are too big for the card, so they open from the bottom.
  const [panel, setPanel] = useState<Panel | null>(null);
  const pendingComment = useRef('');
  const prepareAnswer = () => {
    if (isAnswering) return false;
    const comment = draft.trim();
    if (commentLength(comment) > ANSWER_COMMENT_LIMIT) {
      onTooLong();
      return false;
    }
    if (!onBeginAnswer()) return false;
    pendingComment.current = comment;
    return true;
  };
  const choose = (optionId: string) => {
    if (!prepareAnswer()) return;
    const comment = pendingComment.current;
    swipe.current?.fly('right', () => onAnswer(optionId, comment));
  };
  // hold is only for ChatComposer's own clear after submit. Enter does not clear the field, so holding it would swallow the next delete.
  const submitWritten = (text: string, hold: boolean) => {
    if (hold) onHoldDraft();
    if (commentLength(text) > ANSWER_COMMENT_LIMIT) {
      onTooLong();
      return;
    }
    if (isAnswering || !onBeginAnswer()) return;
    swipe.current?.fly('right', () => onAnswer(null, text));
  };
  return (
    <div className="decide-enter">
    <Swipeable ref={swipe} rightLabel={recommended?.label}
      beforeRight={recommended ? prepareAnswer : undefined}
      onRight={recommended ? () => onAnswer(recommended.id, pendingComment.current) : undefined}
      onLeft={onLater}>
      <Card padding={5} elevation="med">
        <VStack gap={4}>
          <HStack gap={2} align="center" justify="between" wrap="wrap">
            <Badge variant="neutral" label={`${card.agent.name} · ${card.agent.where}`} />
            <HStack gap={2} align="center">
              <DueBadge due={card.due} />
              <Text type="supporting">{ago(card.created_at)}</Text>
            </HStack>
          </HStack>

          <VStack gap={3}>
            {([['Task', card.task], ['Progress', card.progress], ['Blocked', card.blocked]] as const).map(([label, text]) => (
              <VStack key={label} gap={0.5}>
                <Text type="label" color="secondary">{label}</Text>
                <Text>{text}</Text>
              </VStack>
            ))}
          </VStack>

          <Heading level={2}>{card.question}</Heading>

          {(card.links.length > 0 || card.canvas || card.details) && (
            <HStack gap={2} align="center" justify="between" wrap="wrap" data-noswipe>
              <HStack gap={2} wrap="wrap">
                {card.links.map((link, index) => {
                  const host = linkHost(link.url);
                  return (
                    <div key={`${index}-${link.url}`}>
                      <HStack gap={1} align="center">
                        {linkIcon[link.kind]}
                        <Link href={link.url} isExternalLink>{link.label}</Link>
                        {host && <Text type="supporting">{host}</Text>}
                      </HStack>
                    </div>
                  );
                })}
              </HStack>
              <div className="decide-panel-buttons"><HStack gap={2} justify="end">
                {card.canvas && <Button label="Diagram" size="sm" icon={<Icon icon="mivki:canvas" />} onClick={() => setPanel('canvas')} />}
                {card.details && <Button label="Details" size="sm" icon={<Icon icon="mivki:doc" />} onClick={() => setPanel('details')} />}
              </HStack></div>
            </HStack>
          )}

          <div data-noswipe className="decide-answer">
            <Card variant="muted" padding={3}>
              <VStack gap={2}>
                <HStack justify="between" align="center">
                  <Text type="label" color="secondary">Answer</Text>
                  <Button label="Later" variant="ghost" size="sm" icon={<AnimatedIcon icon={ArrowLeftIcon} size={16} />}
                    onClick={() => swipe.current?.fly('left', onLater)} />
                </HStack>
                {card.options.map(option => (
                  <ClickableCard key={option.id} label={`Choose ${option.label}`} padding={3}
                    variant={option.id === card.recommended ? 'blue' : 'default'}
                    onClick={() => choose(option.id)}>
                    <VStack gap={1}>
                      <HStack gap={2} align="center" wrap="wrap">
                        <Text weight="semibold">{option.label}</Text>
                        {option.id === card.recommended && <Badge variant="info" label="Recommended" />}
                      </HStack>
                      <Text type="supporting">{option.effect}</Text>
                    </VStack>
                  </ClickableCard>
                ))}
                {card.recommended && card.reason &&
                  <Text type="supporting">{`Why recommended: ${card.reason}`}</Text>}
                {messages.length > 0 && (
                  <div role="alert">
                    <VStack gap={1}>
                      {messages.map((message, index) => <Text key={`${index}-${message}`}>{message}</Text>)}
                    </VStack>
                  </div>
                )}
                <ChatComposer value={draft} onChange={onDraftChange} density="compact" elevation="none"
                  placeholder={COMPOSER_PLACEHOLDER}
                  isDisabled={isAnswering}
                  onSubmit={text => submitWritten(text, true)}
                  input={
                    <textarea className="decide-composer" placeholder={COMPOSER_PLACEHOLDER} value={draft} rows={2}
                      readOnly={isAnswering}
                      onChange={event => { if (!isAnswering) onDraftChange(event.target.value); }}
                      onKeyDown={event => {
                        // Confirming an IME conversion reports Enter with isComposing or keyCode 229.
                        if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
                        if (event.key !== 'Enter' || event.shiftKey || isAnswering) return;
                        event.preventDefault();
                        const text = draft.trim();
                        if (text) submitWritten(text, false);
                      }} />
                  } />
              </VStack>
            </Card>
          </div>

        </VStack>
      </Card>
    </Swipeable>
    {card.canvas && (
      <BottomSheet isOpen={panel === 'canvas'} onOpenChange={open => setPanel(open ? 'canvas' : null)} label="Diagram" height="hug">
        <SheetHeader onClose={() => setPanel(null)} />
        <div className="cv-sheet"><Canvas spec={card.canvas} /></div>
      </BottomSheet>
    )}
    {card.details && (
      <BottomSheet isOpen={panel === 'details'} onOpenChange={open => setPanel(open ? 'details' : null)} label="Details" height="tall">
        <SheetHeader title="Details" onClose={() => setPanel(null)} />
        <div className="decide-details">
          <Markdown density="compact" headingLevelStart={3} components={{image: MarkdownImage}}>{card.details}</Markdown>
        </div>
      </BottomSheet>
    )}
    </div>
  );
}

/**
 * Title and close control for a sheet opened from the bottom.
 * On a phone, drag down or tap outside to close; on a desktop, this close button does it.
 * The row stays put while the body scrolls.
 */
function SheetHeader({title, onClose}: {title?: string; onClose: () => void}) {
  return (
    <div className="decide-sheet-header">
      <HStack justify={title ? 'between' : 'end'} align="center">
        {title && <Heading level={2}>{title}</Heading>}
        <IconButton label="Close" tooltip="Close" variant="ghost" icon={<Icon icon="close" />} onClick={onClose} />
      </HStack>
    </div>
  );
}

/** Tracks a horizontal drag. Right calls onRight; left calls onLeft. Without onRight, a right drag snaps back. */
type SwipeProps = {
  onLeft: () => void;
  onRight?: () => void;
  beforeRight?: () => boolean;
  rightLabel?: string;
  children: ReactNode;
  ref?: Ref<CardHandle>;
};

function Swipeable({onLeft, onRight, beforeRight, rightLabel, children, ref: handle}: SwipeProps) {
  const ref = useRef<HTMLDivElement>(null);
  const leftStamp = useRef<HTMLDivElement>(null);
  const rightStamp = useRef<HTMLDivElement>(null);
  const drag = useRef<{x: number; y: number; dx: number; active: boolean} | null>(null);

  const move = (dx: number, animate: boolean) => {
    const element = ref.current;
    if (!element) return;
    element.style.transition = animate ? `transform ${FLY_MS}ms ease, opacity ${FLY_MS}ms ease` : 'none';
    element.style.transform = dx ? `translateX(${dx}px) rotate(${dx / 30}deg)` : '';
    element.style.opacity = Math.abs(dx) > 400 ? '0' : '';
    if (leftStamp.current) leftStamp.current.style.opacity = String(Math.min(1, Math.max(0, -dx / 90)));
    if (rightStamp.current) rightStamp.current.style.opacity = String(Math.min(1, Math.max(0, dx / 90)));
  };
  // Call then after the card has flown off. Reset afterward in case the same card stays (the only card, marked later).
  const fly = (direction: 'left' | 'right', then: () => void) => {
    const finish = () => { then(); requestAnimationFrame(() => move(0, false)); };
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { finish(); return; }
    move(direction === 'right' ? 560 : -560, true);
    setTimeout(finish, FLY_MS);
  };
  useImperativeHandle(handle, () => ({fly}));
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('[data-noswipe], a, button, textarea, input')) return;
    drag.current = {x: event.clientX, y: event.clientY, dx: 0, active: false};
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state) return;
    state.dx = event.clientX - state.x;
    if (!state.active) {
      if (Math.abs(state.dx) < 12) return;
      if (Math.abs(event.clientY - state.y) > Math.abs(state.dx)) { drag.current = null; return; }
      state.active = true;
    }
    move(state.dx, false);
  };
  const onPointerUp = () => {
    const state = drag.current;
    drag.current = null;
    if (!state?.active) return;
    if (state.dx > SWIPE_DISTANCE && onRight) {
      if (beforeRight && !beforeRight()) {
        move(0, true);
        return;
      }
      fly('right', onRight);
    } else if (state.dx < -SWIPE_DISTANCE) fly('left', onLeft);
    else move(0, true);
  };
  // The browser cancelled the gesture (scroll, alert). Reset only; a cancel is not an answer.
  const onPointerCancel = () => {
    drag.current = null;
    move(0, false);
  };
  return (
    <div ref={ref} className="decide-swipe" onPointerDown={onPointerDown} onPointerMove={onPointerMove}
      onPointerUp={onPointerUp} onPointerCancel={onPointerCancel} onDragStart={event => event.preventDefault()}>
      <div ref={leftStamp} className="decide-stamp decide-stamp-left" aria-hidden="true"><Badge variant="neutral" label="Later" /></div>
      {rightLabel && <div ref={rightStamp} className="decide-stamp decide-stamp-right" aria-hidden="true"><Badge variant="info" label={rightLabel} /></div>}
      {children}
    </div>
  );
}
