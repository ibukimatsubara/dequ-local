import type {ReactNode} from 'react';
import {AppShell} from '@astryxdesign/core/AppShell';
import {Heading} from '@astryxdesign/core/Heading';
import {VStack} from '@astryxdesign/core/Stack';
import {Text} from '@astryxdesign/core/Text';
import {TopNav, TopNavItem} from '@astryxdesign/core/TopNav';

type Props = {
  appName?: string;
  title?: string;
  description?: string;
  navigation: readonly {href: string; label: string}[];
  actions?: ReactNode;
  children: ReactNode;
};

export function AppFrame({appName = 'Mivki UI', title, description, navigation, actions, children}: Props) {
  return (
    <AppShell height="auto" variant="surface" topNav={
      <TopNav label="App navigation" heading={<Text weight="semibold">{appName}</Text>}
        startContent={navigation.length > 0 ? <>{navigation.map(item =>
          <TopNavItem key={item.href} href={item.href} label={item.label} />)}</> : undefined}
        endContent={actions} />
    }>
      <div className="page-content">
        <VStack gap={6}>
          {title && <VStack gap={2}>
            <Heading level={1}>{title}</Heading>
            {description && <Text color="secondary">{description}</Text>}
          </VStack>}
          {children}
        </VStack>
      </div>
    </AppShell>
  );
}
