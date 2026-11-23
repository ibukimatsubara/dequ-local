import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {Theme} from '@astryxdesign/core/theme';
import {Icon} from '@astryxdesign/core/Icon';
import {mivkiTheme} from './mivkiTheme';

it('loads both extended action names and inherited common names as SVG from the theme', () => {
  render(<Theme theme={mivkiTheme}>
    <Icon icon="mivki:add" label="Add" />
    <Icon icon="mivki:edit" label="Edit" />
    <Icon icon="mivki:save" label="Save" />
    <Icon icon="mivki:delete" label="Delete" />
    <Icon icon="search" label="Search" />
  </Theme>);
  for (const name of ['Add', 'Edit', 'Save', 'Delete', 'Search']) {
    expect(screen.getByRole('img', {name}).querySelector('svg')).not.toBeNull();
  }
});
