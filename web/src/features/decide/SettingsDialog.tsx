import {useState, type FormEvent, type ReactNode} from 'react';
import {Button} from '@astryxdesign/core/Button';
import {Card} from '@astryxdesign/core/Card';
import {Dialog, DialogHeader} from '@astryxdesign/core/Dialog';
import {Divider} from '@astryxdesign/core/Divider';
import {SegmentedControl, SegmentedControlItem} from '@astryxdesign/core/SegmentedControl';
import {HStack, StackItem, VStack} from '@astryxdesign/core/Stack';
import {Switch} from '@astryxdesign/core/Switch';
import {Text} from '@astryxdesign/core/Text';
import {TextInput} from '@astryxdesign/core/TextInput';
import {AnimatedIcon} from '../../components/icons/AnimatedIcon';
import {BellIcon} from '../../components/icons/animated/bell';
import {MoonIcon} from '../../components/icons/animated/moon';
import {SunIcon} from '../../components/icons/animated/sun';
import type {NotifySetting} from './useNewDecisionNotice';

export type Mode = 'light' | 'dark';
type Props = {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  notify: NotifySetting;
  hasToken: boolean;
  onChangeToken: (token: string) => void;
  onRemoveToken: () => void;
};

/**
 * One settings row: icon, name, and description on the left, the control on the right.
 * The row shows the name, so the control uses isLabelHidden (same arrangement as the Astryx settings-dialog template).
 */
function SettingsRow({icon, title, description, control}: {icon: ReactNode; title: string; description?: string; control: ReactNode}) {
  return (
    <HStack padding={4} gap={3} align="center" data-animate-icons>
      <StackItem size="fill">
        <HStack gap={3} align="start">
          {/* Keep the icon on the title line even when a description wraps below it. */}
          <span className="decide-row-icon">{icon}</span>
          <VStack gap={0.5}>
            <Text weight="medium">{title}</Text>
            {description && <Text type="supporting">{description}</Text>}
          </VStack>
        </HStack>
      </StackItem>
      {control}
    </HStack>
  );
}

/** Settings live here. Other screens do not grow their own settings controls. */
export function SettingsDialog({isOpen, onOpenChange, mode, onModeChange, notify, hasToken, onChangeToken, onRemoveToken}: Props) {
  const [nextToken, setNextToken] = useState('');
  const notifyHint = notify.isBlocked ? 'Notifications are blocked in the browser settings.'
    : !notify.isAvailable ? 'Notifications are available when you open the app over https.'
    : 'Get notified when a new decision is waiting.';
  const changeToken = (event: FormEvent) => {
    event.preventDefault();
    const next = nextToken.trim();
    if (!next) return;
    setNextToken('');
    onChangeToken(next);
  };
  return (
    <Dialog isOpen={isOpen} onOpenChange={onOpenChange}>
      {/* Do not set padding on Dialog. It stacks with the header spacing and shifts only the title. */}
      <VStack gap={4}>
        <DialogHeader title="Settings" onOpenChange={onOpenChange} hasDivider={false} />
        <Card padding={0} width="100%" variant="muted">
          <SettingsRow icon={<AnimatedIcon icon={BellIcon} size={18} />} title="Notifications" description={notifyHint}
            control={<Switch label="Notify me about new decisions" isLabelHidden value={notify.isEnabled}
              isDisabled={!notify.isAvailable || notify.isBlocked} onChange={() => { void notify.toggle(); }} />} />
          <Divider variant="subtle" />
          <SettingsRow icon={<AnimatedIcon icon={mode === 'dark' ? MoonIcon : SunIcon} size={18} />} title="Appearance"
            control={
              <SegmentedControl label="Appearance" size="sm" value={mode} onChange={value => onModeChange(value as Mode)}>
                <SegmentedControlItem value="light" label="Light" />
                <SegmentedControlItem value="dark" label="Dark" />
              </SegmentedControl>} />
          {hasToken && (
            <>
              <Divider variant="subtle" />
              <form onSubmit={changeToken}>
                <VStack padding={4} gap={3}>
                  <VStack gap={0.5}>
                    <Text weight="medium">Token</Text>
                    <Text type="supporting">Sent with every request. Changing it drops cached decisions.</Text>
                  </VStack>
                  <TextInput label="New token" type="password" value={nextToken} onChange={setNextToken} />
                  <HStack gap={2} wrap="wrap">
                    <Button label="Change token" type="submit" variant="primary" isDisabled={!nextToken.trim()} />
                    <Button label="Remove token" variant="destructive" onClick={onRemoveToken} />
                  </HStack>
                </VStack>
              </form>
            </>
          )}
        </Card>
      </VStack>
    </Dialog>
  );
}
