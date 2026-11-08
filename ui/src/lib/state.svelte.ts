import { SvelteSet } from 'svelte/reactivity';
import { actedLevels, type ActedLog, type OpenGroups, type Phase } from './logic';
import type {
  ApiErrorBody, ApkEstimate, AppsPlanView, AppsProgressView, AppsResultView, WhatsappView, BackupResultView, CopyView, InventoryView, RestorePlanView, RestoreProgressView, RestoreResultView, TapRequest, TelPlanView, TelProgressView, TelResultView, TransferOrderView, TransferProgress, TransferSelection, UploadChoiceView, ApkQuestion, Category, ConsoleEntry, DeviceEntry, EtaView, HistoryView, IncidentDone, Level, MirrorState, OrderResult, PhoneCard,
  PlanView, Question, ReportResult, ScanView, Settings, ShareState, ShotsView, ShotView, StepEvent, UndoDone, UndoSite, UpdateView, UserWait, Verdict, WhoView,
} from './types';

/** Zakładka kroku Naprawa: lista aplikacji albo stan telefonu. */
export type RepairTab = 'apps' | 'phone';
/** Zakładki Historii: naprawy telefonu / przeniesienia danych (zlecenia ZS wszystkich telefonów). */
export type HistoryTab = 'orders' | 'transfers';
export type Screen = 'main' | 'history' | 'settings' | 'explorer';
/** Kategorie ekranu Ustawienia w kolejności kolumny (spec ustawień §4). */
export type SettingsCategory = 'general' | 'repair' | 'transfer' | 'explorer' | 'service' | 'privacy' | 'program';
const ORDER_KINDS = ['exec', 'resume', 'undo'];

export const EMPTY_TRANSFER_SELECTION: TransferSelection = {
  contacts: false, sms: false, mms: false, calls: false, categories: [], others: [], apps: [],
};

export const emptyRestore = (): RestoreState => ({ plan: null, copy: null,
  choice: { groups: [], apks_on: [], verify_hash: false, tel: [], apps: [] }, apps: null, progress: null, result: null, sameRecent: false,
  resumable: false, tel: null, telProgress: null, telResult: null, telError: null, tap: null, tapPackage: null,
  appsProgress: null, appsResult: null, appsError: null, order: null, whatsapp: null, whatsappRestored: false, reinstallDone: false, reinstallGaveUp: false, awaitBlock: false });

/** Wgrywanie kopii na nowy telefon: plan z mostu, wybór serwisanta, postęp i wynik. */
export interface RestoreState {
  plan: RestorePlanView | null;
  /** Wgrywana kopia (zanim przyjdzie plan — z listy kopii). */
  copy: CopyView | null;
  choice: UploadChoiceView;
  /** Aplikacje z kopii (null — plan jeszcze nie przyszedł albo most bez aplikacji). */
  apps: AppsPlanView | null;
  progress: RestoreProgressView | null;
  result: RestoreResultView | null;
  /** Ten sam telefon co w kopii i kopia młodsza niż 24 h — ostrzeżenie, domyślnie „Nie”. */
  sameRecent: boolean;
  /** Na tym telefonie jest przerwane wgrywanie tej kopii — „Wgraj” je wznowi. */
  resumable: boolean;
  /** Kontakty, wiadomości i połączenia z kopii (null — kopia bez telefonii albo plan jeszcze nie przyszedł). */
  tel: TelPlanView | null;
  telProgress: TelProgressView | null;
  telResult: TelResultView | null;
  /** Klucz błędu telefonii po plikach (`tel_error`): wynik plików zostaje, telefonia ma własny baner. */
  telError: string | null;
  /** Prośba o stuknięcie na telefonie (`transfer:tap`) — także w czasie przywracania ustawień telefonu. */
  tap: TapRequest | null;
  /** Poprzednia domyślna aplikacja SMS (pakiet), której oddajemy rolę. */
  tapPackage: string | null;
  /** Postęp etapu „Aplikacje” (także dokończenia po blokadzie Xiaomi). */
  appsProgress: AppsProgressView | null;
  /** Wynik instalacji aplikacji (null — bez aplikacji albo błąd `appsError`); `transfer:apps_done` zastępuje go w miejscu. */
  appsResult: AppsResultView | null;
  /** Klucz błędu etapu „Aplikacje” (`apps_error`): reszta wyniku zostaje. */
  appsError: string | null;
  /** Numer ZS zlecenia przeniesienia (null — most bez zlecenia: bez protokołu). */
  order: string | null;
  /** Ramka WhatsApp wyniku (null — WhatsApp nie wybrany albo pliki niewgrane). */
  whatsapp: WhatsappView | null;
  /** Pole „Czaty przywrócone” — to, co zapisano w zleceniu. */
  whatsappRestored: boolean;
  /** Dokończenie aplikacji po odblokowaniu Xiaomi już uruchomiono (raz na wynik). */
  reinstallDone: boolean;
  /** Dokończenie aplikacji nie może się udać (błąd trwały): bez obietnicy „sprawdzę sam”, powód w wierszu. */
  reinstallGaveUp: boolean;
  /** Dokończenie wróciło z nadal zablokowanymi aplikacjami: następne ruszy dopiero po nowym przejściu zablokowane → odblokowane. */
  awaitBlock: boolean;
}

/** Przywracanie ustawień telefonu po przerwanym wgrywaniu (`phone_cleanup`): `ok` — wynik ostatniej próby. */
export interface CleanupState {
  /** Telefon, którego dotyczy sprzątanie (`transfer:cleanup_started`); null — żadnego. */
  serial: string | null;
  running: boolean;
  ok: boolean | null;
}

/** Przenoszenie danych: inwentarz starego telefonu, wybór, postęp kopii i kopie na komputerze. */
export interface TransferState {
  inventory: InventoryView | null;
  /** Niedokończona kopia tego telefonu (start_backup ją wznowi). */
  resumable: CopyView | null;
  selection: TransferSelection;
  progress: TransferProgress | null;
  /** Telefon odłączony w trakcie kopii albo wgrywania — most czeka na ponowne podłączenie. */
  waiting: boolean;
  result: BackupResultView | null;
  /** Kopia z `transfer:done` (ile dni do usunięcia). */
  copy: CopyView | null;
  copies: CopyView[];
  /** Zlecenia ZS przeniesień (Historia → Przeniesienia), najnowsze pierwsze. */
  orders: TransferOrderView[];
  /** Zlecenie, któremu Historia doinstalowuje aplikacje (zadanie `restore_apps` trwa). */
  appsBusy: string | null;
  /** Krótka uwaga w wierszu zlecenia po nieudanym doinstalowaniu (klucz błędu) — bez banera. */
  appsNotes: Record<string, string>;
  restore: RestoreState;
  cleanup: CleanupState;
}

export class AppState {
  phase = $state<Phase>('connect');
  screen = $state<Screen>('main');
  settings = $state<Settings>({ lang: 'pl', mode: 'simple', adb_path: null, backups_dir: null, report_pdf_dir: null, theme: 'system', mirror_auto: false,
    apk_cache_limit_gb: 10, apk_cache_clear_after_repair: false, select_level: 'silence', retention_days: 60,
    check_updates: true, dismissed_update: null, last_run_version: null,
    welcome_version: 1, welcome_current: 1, telemetry: false, telemetry_packages: false, telemetry_id: null,
    telemetry_delete_pending: false, donate_reminders: true, apk_mode_default: 'ask',
    transfers_dir: null, transfer_keep_days: 7, transfer_apps_default: true, verify_copies: false,
    explorer_hidden: false, explorer_dest_mode: 'last', explorer_dest_fixed: null, report_open: true,
    explorer_recent_phones: 0 });
  settingsLoaded = $state(false);  // ekran powitalny dopiero po odczycie ustawień
  /** Ostatnio otwarta kategoria Ustawień — pamiętana do zamknięcia okna. */
  settingsCategory = $state<SettingsCategory>('general');
  /** Rośnie przy każdym `openSettings(kategoria)` — ekran kończy wtedy wyszukiwanie, także gdy kategoria się nie zmienia. */
  settingsOpened = $state(0);
  /** Chwila (Date.now()) ostatniego udanego zapisu ustawień; 0 = jeszcze nic. Ekran pokazuje wtedy „✓ Zapisano”. */
  settingsSaved = $state(0);
  /** Dane serwisu bez nazwy — kropka przy kategorii „Serwis i protokoły”. */
  serviceNameMissing = $state(false);
  devices = $state<DeviceEntry[]>([]);
  devicesError = $state<string | null>(null);
  knownSerials = $state<string[]>([]);
  serial = $state<string | null>(null);
  client = $state('');
  scanStage = $state<string | null>(null);
  device = $state<PhoneCard | null>(null);
  scan = $state<ScanView | null>(null);
  apk = $state({ done: 0, total: 0, running: false, changed: [] as string[], eta: null as number | null });
  apkEstimate = $state<ApkEstimate | null>(null);
  /** Czas analizy całego telefonu (przycisk „Przeanalizuj wszystko”); szacunek zaznaczonych go nie zmienia. */
  apkFullEta = $state<EtaView | null>(null);
  apkQuestion = $state<ApkQuestion | null>(null);
  selectionEta = $state<EtaView | null>(null);
  showSystem = $state(false);
  /** Czy bieżąca analiza APK obejmuje wszystko (przycisk „Przerwij i szukaj ręcznie”) czy tylko zaznaczone. */
  apkScope = $state<'all' | 'selected'>('all');
  /** Serwisant wybrał pełną analizę po pytaniu o tryb — od tej chwili werdykty heurystyk są widoczne. */
  apkFullChosen = $state(false);
  interrupted = $state<string[]>([]);
  selection = $state<Record<string, Level>>({});
  touched = $state<string[]>([]);
  unlocked = $state<string[]>([]);
  /** Zaznaczone poprawki „Stanu telefonu” (identyfikatory z `device_checks`); nic nie jest zaznaczone z góry. */
  fixes = new SvelteSet<string>();
  verdictFilter = $state<Verdict | 'all'>('all');
  query = $state('');
  categoryFilter = $state<Category[]>([]);
  sourceFilter = $state<string | null>(null);
  expanded = $state<string[]>([]);
  focused = $state<string | null>(null);
  /** Rozwinięte/zwinięte grupy werdyktu na ekranie Naprawa; puste = domyślne trybu (logic.groupOpen). */
  openGroups = $state<OpenGroups>({});
  /** Aktywna zakładka kroku Naprawa; żyje do nowego skanu / powrotu do Połącz (zmiana kroku jej nie rusza). */
  repairTab = $state<RepairTab>('apps');
  /** Prawy panel pokazuje „Znajdź źródło reklamy" zamiast planu / szczegółów. */
  diagnostics = $state(false);
  who = $state<WhoView | null>(null); // wynik „Kto to wyświetla?” — żyje do nowego skanu
  /** „Szczegóły techniczne" w panelu Eksperta — pamiętane do zamknięcia programu. */
  detailsOpen = $state(false);
  plan = $state<PlanView | null>(null);
  share = $state<ShareState | null>(null); // kod QR planu dla klienta (spec plan-qr §6)
  consent = $state(false);
  planChanged = $state(false); // `execute` odrzucił zgodę: plan inny niż pokazany
  job = $state<{ id: string; kind: string } | null>(null);
  incident = $state<{ recording: boolean; marks: number; result: IncidentDone | null }>({ recording: false, marks: 0, result: null });
  order = $state<string | null>(null);
  execPlan = $state<PlanView | null>(null);
  steps = $state<StepEvent[]>([]);
  /** Program czeka na ruch serwisanta na telefonie (administrator urządzenia albo przełącznik powiadomień). */
  userWait = $state<(UserWait & { since: number }) | null>(null);
  question = $state<Question | null>(null);
  verifying = $state(false);
  stopping = $state(false);
  stopped = $state(false);
  result = $state<OrderResult | null>(null);
  donateBanner = $state(false); // przypomnienie o wsparciu na ekranie wyniku (spec kroku J §6.1)
  /** Co już zrobiono na tym telefonie od skanu, zlecenie po zleceniu (powrót do naprawy, cofanie aplikacji). */
  actedLog = $state<ActedLog>({});
  /** Trwające cofanie (undo:done zdejmuje cofnięte z actedLog); action_id → null, bo cofa tylko krok. */
  undoing = $state<{ order: string; pkg: string | null } | null>(null);
  /** Aplikacja cofana z listy wyników — tam pokazujemy postęp i błędy. */
  undoTarget = $state<string | null>(null);
  get acted(): Record<string, Level> {
    return actedLevels(this.actedLog);
  }
  disconnectedOrder = $state<string | null>(null);
  history = $state<HistoryView | null>(null);
  /** Zakładka Historii: naprawy wybranego telefonu albo przeniesienia danych wszystkich telefonów. */
  historyTab = $state<HistoryTab>('orders');
  undoSteps = $state<StepEvent[]>([]);
  undoResult = $state<UndoDone | null>(null);
  /** Kolejka witryn bieżącego cofania (`undo:sites`); null — cofanie nie ma ekranów witryn. */
  undoSites = $state<UndoSite[] | null>(null);
  /** Nie udało się otworzyć strony na telefonie (`open_site`): baner ostrzeżenia w historii. */
  openSiteFailed = $state(false);
  reportBusy = $state<string | null>(null);
  reports = $state<Record<string, ReportResult>>({});
  mirror = $state<{ available: boolean; serial: string | null; state: MirrorState; reason: string | null; blocked: boolean; awakeBlocked: boolean }>(
    { available: false, serial: null, state: 'stopped', reason: null, blocked: false, awakeBlocked: false });
  shots = $state<Record<string, ShotsView>>({});
  lastShot = $state<ShotView | null>(null);
  lastShotSerial = $state<string | null>(null);
  shotCount = $state(0);
  shotBusy = $state(false);
  consoleOpen = $state(false);
  console = $state<ConsoleEntry[]>([]);
  consoleWarned = $state(false);
  error = $state<ApiErrorBody | null>(null);
  closeRequested = $state(false);
  closingAfterStep = $state(false);  // zamknięcie czeka na koniec bieżącego kroku zlecenia
  update = $state<UpdateView | null>(null);
  updateDialog = $state(false);
  updateProgress = $state<{ done: number; total: number | null } | null>(null);
  updateError = $state<ApiErrorBody | null>(null);
  /** „Zaktualizowano do …” zamknięte w tej sesji. */
  updatedSeen = $state(false);
  fatal = $state<string | null>(null);
  crashStartup = $state<string[]>([]);
  crashDialog = $state<string | null>(null);
  crashAdb = $state(false);
  crashComment = $state('');
  crashPreview = $state<Record<string, unknown> | null>(null);
  crashHasAdb = $state(false);
  crashSending = $state(false);
  crashSent = $state<string | null>(null);
  crashError = $state<ApiErrorBody | null>(null);
  fatalCrash = $state<string | null>(null);
  transfer = $state<TransferState>({ inventory: null, resumable: null, selection: { ...EMPTY_TRANSFER_SELECTION },
    progress: null, waiting: false, result: null, copy: null, copies: [], orders: [], appsBusy: null, appsNotes: {}, restore: emptyRestore(),
    cleanup: { serial: null, running: false, ok: null } });

  get orderRunning(): boolean {
    return this.job !== null && ORDER_KINDS.includes(this.job.kind);
  }

  /** Pełna analiza (po skanie albo „Przeanalizuj wszystko”) — z niej można przejść do trybu ręcznego. */
  get canStopToManual(): boolean {
    return this.job?.kind === 'apk' && this.apkScope === 'all';
  }
}
