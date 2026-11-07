import type { SettingsCategory } from '../../lib/state.svelte';
import type { IconName } from '../../ui/Icon.svelte';

export type { SettingsCategory };

export type CategoryInfo = { id: SettingsCategory; icon: IconName; labelKey: string; leadKey: string };

const entry = (id: SettingsCategory, icon: IconName): CategoryInfo =>
  ({ id, icon, labelKey: `settings.cat.${id}`, leadKey: `settings.lead.${id}` });

/** Kolejność kolumny kategorii (spec ustawień §4). */
export const CATEGORIES: CategoryInfo[] = [
  entry('general', 'sliders-horizontal'),
  entry('repair', 'wrench'),
  entry('transfer', 'arrow-left-right'),
  entry('explorer', 'folder'),
  entry('service', 'file-text'),
  entry('privacy', 'lock'),
  entry('program', 'info'),
];
