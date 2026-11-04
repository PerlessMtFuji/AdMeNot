import type { Lang } from '../types';
import en from './en.json';
import pl from './pl.json';

type Dict = { [key: string]: string | Dict };
const dictionaries: Record<Lang, Dict> = { pl, en };

// Klucze składane dynamicznie (test sprawdza, że są w obu słownikach).
export const ERROR_KEYS = ['adb_missing', 'unauthorized', 'offline', 'disconnected', 'timeout',
  'adb_error', 'action_error', 'busy', 'wrong_device', 'device_mismatch', 'no_scan', 'no_device', 'unknown_order',
  'nothing_to_resume', 'nothing_to_do', 'no_target', 'bad_request', 'logo_missing', 'logo_type',
  'logo_size', 'internal', 'mirror_missing', 'mirror_failed', 'unknown_screenshot', 'shot_limit',
  'data_too_new', 'retired', 'unknown_crash', 'device_busy', 'plan_changed',
  'transfer_no_inventory', 'transfer_disk_full', 'transfer_wrong_device', 'transfer_too_many_disconnects', 'transfer_failed',
  'transfer_in_use', 'transfer_phone_full', 'transfer_copy_missing', 'transfer_no_plan',
  'explorer_busy', 'explorer_offline', 'explorer_denied', 'explorer_missing', 'explorer_exists', 'explorer_bad_name',
  'explorer_not_open', 'explorer_no_dest', 'explorer_not_folder'] as const;
// Błędy wgrywania kopii, których wspólny z kopią tekst mówi o kopii — dla zadań wgrywania `transfer.restore.error.*`.
export const RESTORE_ERROR_KEYS = ['transfer_wrong_device', 'transfer_too_many_disconnects', 'transfer_failed'] as const;
export const RESTORE_JOB_KINDS = ['restore_plan', 'restore'] as const;

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
  'shot.count', 'apk_cache.estimate', 'checks.to_fix', 'checks.picked', 'history.sites_restored',
  'undo.done_collapsed', 'transfer.apps_skipped', 'transfer.apps_suspicious', 'transfer.files', 'transfer.messages',
  'transfer.folders', 'transfer.categories', 'transfer.progress_files', 'transfer.expires', 'transfer.days_left',
  'transfer.unreadable_files', 'transfer.restore.missing', 'transfer.restore.apk_skipped', 'transfer.restore.tel.synced',
  'transfer.restore.tel.messenger', 'explorer.summary', 'explorer.folders', 'explorer.skipped', 'explorer.leftovers',
  'explorer.selection.count', 'explorer.preview.lines', 'explorer.task.copied', 'explorer.task.uploaded', 'explorer.task.failed_pc',
  'explorer.task.failed_phone', 'explorer.task.skipped', 'explorer.task.renamed', 'explorer.task.damaged',
  'explorer.task.more', 'explorer.problems.path_too_long_pc', 'explorer.problems.path_too_long_phone',
  'explorer.drop.items'] as const;


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
