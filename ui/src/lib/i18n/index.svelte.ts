import type { Lang } from '../types';
import en from './en.json';
import pl from './pl.json';

type Dict = { [key: string]: string | Dict };
const dictionaries: Record<Lang, Dict> = { pl, en };

// Klucze składane dynamicznie (test sprawdza, że są w obu słownikach).
export const ERROR_KEYS = ['adb_missing', 'unauthorized', 'offline', 'disconnected', 'timeout',
  'adb_error', 'action_error', 'busy', 'wrong_device', 'no_scan', 'no_device', 'unknown_order',
  'nothing_to_resume', 'nothing_to_do', 'no_target', 'bad_request', 'logo_missing', 'logo_type',
  'logo_size', 'internal', 'mirror_missing', 'mirror_failed', 'unknown_screenshot', 'shot_limit',
  'data_too_new', 'retired', 'unknown_crash'] as const;
// Błędy okna aktualizacji (klucze `update.error.*`).
export const UPDATE_ERROR_KEYS = ['update_download', 'update_corrupt', 'update_launch_failed', 'busy',
  'update_none', 'internal'] as const;
// Błędy okna raportu błędu (klucze `crash.error.*`).
export const CRASH_ERROR_KEYS = ['crash_offline', 'crash_rejected', 'unknown_crash', 'internal'] as const;
export const SCAN_STAGES = ['identify', 'packages', 'collectors', 'score', 'apk'] as const;
export const LEVEL_KEYS = ['silence', 'disable', 'remove', 'review', 'none'] as const;
// Rodziny kluczy z formami liczby mnogiej (one/few/many/other w obu słownikach).
export const PLURAL_KEYS = ['results.title', 'results.safe', 'expert.days', 'panel.apps',
  'exec.apps', 'exec.steps', 'history.did.remove', 'history.did.disable', 'history.did.silence',
  'shot.count', 'apk_cache.estimate'] as const;

class I18n {
  lang = $state<Lang>('pl');
}

export const i18n = new I18n();

function lookup(dict: Dict, key: string): string | undefined {
  let node: string | Dict | undefined = dict;
  for (const part of key.split('.')) {
    if (typeof node !== 'object' || node === null) return undefined;
    node = node[part];
  }
  return typeof node === 'string' ? node : undefined;
}

export function t(key: string, params: Record<string, string | number> = {}): string {
  const text = lookup(dictionaries[i18n.lang], key) ?? lookup(dictionaries.pl, key) ?? key;
  return text.replace(/\{(\w+)\}/g, (all, name: string) =>
    name in params ? String(params[name]) : all);
}

export function tp(key: string, count: number, params: Record<string, string | number> = {}): string {
  const form = new Intl.PluralRules(i18n.lang).select(count);
  return t(`${key}.${form}`, { count, ...params });
}
