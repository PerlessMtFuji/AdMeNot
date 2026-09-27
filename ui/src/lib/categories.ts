import type { Category } from './types';

export const CATEGORY_ORDER: Category[] = ['ads', 'notif', 'removal', 'data', 'disguise', 'background', 'origin'];

// Nazwy ikon z ui/Icon.svelte (Task 4).
export const CATEGORY_ICON: Record<Category | 'combo', string> = {
  ads: 'megaphone',
  notif: 'bell-ring',
  removal: 'lock',
  data: 'eye',
  disguise: 'venetian-mask',
  background: 'clock',
  origin: 'download',
  combo: 'zap',
};

export function categoryKey(category: Category | 'combo'): string {
  return `category.${category}`;
}
