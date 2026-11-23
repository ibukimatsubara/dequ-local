import {createElement} from 'react';
import {Bot, CircleDot, Code, FileText, GitMerge, GitPullRequest, Pencil, Plus, Save, Scale, Trash2, User, Workflow} from 'lucide-react';

// Extra actions are named by meaning, and the glyph choice lives in the theme.
// Importing this module keeps the icons through the Astryx theme build.
const iconProps = {size: '1em', 'aria-hidden': true} as const;
export const mivkiIcons = {
  'mivki:add': createElement(Plus, iconProps),
  'mivki:edit': createElement(Pencil, iconProps),
  'mivki:save': createElement(Save, iconProps),
  'mivki:delete': createElement(Trash2, iconProps),
  'mivki:pr': createElement(GitPullRequest, iconProps),
  'mivki:issue': createElement(CircleDot, iconProps),
  'mivki:doc': createElement(FileText, iconProps),
  'mivki:merge': createElement(GitMerge, iconProps),
  'mivki:impl': createElement(Code, iconProps),
  'mivki:policy': createElement(Scale, iconProps),
  'mivki:bot': createElement(Bot, iconProps),
  'mivki:me': createElement(User, iconProps),
  'mivki:canvas': createElement(Workflow, iconProps),
};
