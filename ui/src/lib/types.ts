// Kształt danych z src/admenot/app/present.py i zdarzeń z src/admenot/app/api.py.

export type Lang = 'pl' | 'en';
export type Mode = 'simple' | 'expert';
export type Verdict = 'safe' | 'review' | 'suspicious' | 'malicious';
export type Level = 'silence' | 'disable' | 'remove';
export type Theme = 'system' | 'light' | 'dark';
export type Category = 'ads' | 'notif' | 'removal' | 'data' | 'disguise' | 'background' | 'origin';
export type Severity = 'bad' | 'warn' | 'neutral';
export type ApkMode = 'pending' | 'full' | 'manual' | 'partial';
export type ApkModeDefault = 'ask' | 'full' | 'manual';

export interface Settings {
  lang: Lang;
  mode: Mode;
  adb_path: string | null;
  backups_dir: string | null;
  /** Folder na PDF protokołów (archiwum serwisu); null = katalog programu. */
  report_pdf_dir: string | null;
  theme: Theme;
  mirror_auto: boolean;
  apk_cache_limit_gb: number;
  apk_cache_clear_after_repair: boolean;
  select_level: Level;
  retention_days: number | null;
  check_updates: boolean;
  dismissed_update: string | null;
  last_run_version: string | null;
  welcome_version: number | null;
  welcome_current: number;
  telemetry: boolean;
  telemetry_packages: boolean;
  telemetry_id: string | null;
  telemetry_delete_pending: boolean;
  donate_reminders: boolean;
  apk_mode_default: ApkModeDefault;
  /** Eksplorator: ostatni folder docelowy kopii na komputerze (zapisuje most). */
  explorer_dest?: string | null;
  explorer_view?: 'list' | 'grid' | null;
  explorer_peek?: boolean;
  transfers_dir: string | null;
  transfer_keep_days: number;
  transfer_apps_default: boolean;
  verify_copies: boolean;
  explorer_hidden: boolean;
  explorer_dest_mode: 'last' | 'fixed' | 'ask';
  explorer_dest_fixed: string | null;
  report_open: boolean;
  /** Ile telefonów ma zapamiętane „Ostatnio” w eksploratorze (wypełnia most). */
  explorer_recent_phones: number;
}

export interface TelemetrySample {
  basic: Record<string, unknown>[];
  packages: Record<string, unknown>[];
}

export interface UpdateView {
  available: { version: string; notes: string; size: number } | null;
  dismissed: boolean;
  retired: { min_supported: string; reason: string | null } | null;
  updated_to: string | null;
  updated_notes: string | null;
  installable: boolean;
}

export interface CacheUsage {
  size_bytes: number; free_bytes: number; disk_bytes: number;
  limit_bytes: number; effective_bytes: number; path: string;
}

/** Wynik „Wyczyść teraz”: zwolnione bajty i to, co zostało (pliki zajęte albo pobranie w toku). */
export interface CacheCleared { freed_bytes: number; left_bytes: number }

export interface EtaView {
  eta_s: number | null;
  eta_kind: 'measured' | 'rough' | null;
  eta_min_s: number | null;
  eta_max_s: number | null;
}

export interface ApkEstimate extends EtaView {
  to_fetch_bytes: number; total_bytes: number; apps: number; unknown: number; cached: number;
  largest_bytes: number; limit_bytes: number; effective_bytes: number; free_bytes: number;
}

export interface ApkSpaceQuestion extends ApkEstimate { job_id: string; kind: 'no_space' }
export interface ApkModeQuestion extends Partial<Omit<ApkEstimate, keyof EtaView>>, EtaView { job_id: string; kind: 'mode'; apps: number }
export type ApkQuestion = ApkSpaceQuestion | ApkModeQuestion;

export interface Symptom {
  category: Category;
  severity: Severity;
  text: string;
}

export interface DeviceEntry {
  serial: string;
  state: string;
  model: string | null;
  name?: string | null; // nazwa handlowa z bazy telefonów (Api._identity); brak → kod modelu
  imei?: string | null;
  image?: string | null; // zdjęcie z bazy telefonów (albo sylwetka) jako data URI, jak w PhoneCard
  android?: string | null; // wersja Androida (lista kilku telefonów); starsze mosty jej nie wysyłają
}

export interface DevicesPayload {
  devices: DeviceEntry[];
  error: string | null;
}

export interface PhoneCard {
  serial: string;
  name: string;
  brand: string;
  manufacturer: string;
  model: string;
  market_name: string | null;
  android: string;
  sdk: number;
  patch: string | null;
  uptime_s: number;
  imei?: string | null;
  match: { confidence: string; step: string; matched: string | null } | null;
  image: string;
}

export interface Finding {
  rule_id: string;
  class: string;
  weight: number;
  text: string;
  text_expert: string;
  evidence: Record<string, unknown>;
  category: Category | 'combo';
  label: string;
  basis: 'declared' | 'static' | 'granted' | 'observed' | 'confirmed';
  source: 'phone' | 'apk' | 'ioc';
  locations: string[];
}

export type CapabilityLevels = Record<'declared' | 'code' | 'granted' | 'observed', boolean | null>;

export interface AppView {
  package: string;
  name: string;
  score: number;
  verdict: Verdict;
  verdict_label: string;
  confidence: 'low' | 'medium' | 'high';
  confidence_label: string;
  gaps: { key: string; label: string }[];
  scope: { key: string; label: string }[];
  trusted: boolean;
  incomplete: boolean;
  is_system: boolean;
  /** false: wyłączona na telefonie (`pm disable-user`) — przed tą naprawą albo wcześniej. */
  enabled: boolean;
  from_play: boolean;
  /** Data pierwszej instalacji (ISO) z szybkiego skanu; null — telefon jej nie podał. */
  first_install: string | null;
  installer: string | null;
  is_admin: boolean;
  default_level: Level | null;
  problems: string[];
  findings: Finding[];
  apk_error: string | null;
  icon: string | null;
  ad_sdks: string[] | null;
  symptoms: Symptom[];
  source: { label: string; days: number | null };
  capabilities: { key: string; label: string; levels: CapabilityLevels }[];
}

export type CheckState = 'ok' | 'review' | 'unrecognized';
/** unknown: przeglądarka, której powiadomień program nie umie odczytać (read: 'unsupported'). */
export type BrowserMode = 'per_site' | 'shared' | 'rdp' | 'unknown';

export interface CheckSite {
  host: string;
  origin: string;
  blocked: boolean;
  /** Ma teraz powiadomienie na ekranie telefonu. */
  active: boolean;
  /** Identyfikator poprawki; null — tej witryny nie da się wyciszyć z komputera. */
  fix: string | null;
  fix_label: string | null;
}

export interface CheckBrowser {
  package: string;
  name: string;
  mode: BrowserMode;
  read: 'ok' | 'partial' | 'unrecognized' | 'unsupported';
  /** Firefox bez zdalnego debugowania: lista witryn pojawi się po jego włączeniu. */
  rdp_hint: boolean;
  /** Aktywne powiadomienie witryny ma akcję „Blokuj” (Samsung Internet): instrukcja dla witryny bez poprawki. */
  block_action: boolean;
  all_fix: string | null;
  all_fix_label: string | null;
  sites: CheckSite[];
}

/** Kontrola „Stan telefonu” (etap 1: powiadomienia witryn w przeglądarkach). */
export interface DeviceCheck {
  id: string;
  state: CheckState;
  state_label: string;
  browsers: CheckBrowser[];
}

export interface ScanCounts {
  malicious: number;
  suspicious: number;
  review: number;
  safe: number;
  non_play: number;
  admins: number;
  total: number;
  user: number;
}

export interface ScanView {
  collectors: {
    ok: number;
    total: number;
    failed: { name: string; error: string | null }[];
    /** Kolektory, które zadziałały, ale bez danych dla części aplikacji (starsze nagrania: brak). */
    partial?: { name: string; count: number }[];
  };
  low_behavior_data: boolean;
  apk: { requested: number; analyzed: number; failed: Record<string, string>; stopped_no_space: boolean } | null;
  apps: AppView[];
  device_checks: DeviceCheck[];
  profiles: { others: number[]; known: boolean };
  usage_window_h: number | null;
  counts: ScanCounts;
  apk_mode: ApkMode;
  /** Pakiety przeanalizowane na żądanie (tryb ręczny / częściowy). */
  on_demand: string[];
}

/** `fix`: poprawki „Stanu telefonu” (ustawienia witryn w przeglądarce), nie poziom aplikacji. */
export type PlanLevel = Level | 'fix';

export interface PlanApp {
  package: string;
  name: string;
  level: PlanLevel;
  level_label: string;
  blocked: boolean;
  reason: string | null;
  reason_text: string | null;
  steps: string[];
  warnings: string[];
}

export interface PlanView {
  apps: PlanApp[];
  runnable: number;
  code: string;
}

// offline: tylko przy pierwszej nieudanej wysyłce; false = serwer odpowiedział błędem, a nie brak sieci.
export interface ShareReady { share_id: string; code: string; url: string; mode: 'server' | 'local'; expires: string | null; offline?: boolean }
export interface ShareFailed { share_id: string; code: string; reason: 'too_long' | 'error'; offline?: boolean }
export interface ShareState {
  id: string;
  code: string | null;
  status: 'sending' | 'ready' | 'failed';
  url: string | null;
  mode: 'server' | 'local' | null;
  expires: string | null;
  upgraded: boolean; // kod z trybu lokalnego podmieniony na pełny (z ikonami)
  reason: ShareFailed['reason'] | null;
  offline?: boolean;
}

export type StepStatus = 'running' | 'done' | 'failed' | 'skipped' | 'undone';

export interface StepEvent {
  action_id: number;
  package: string;
  name: string;
  kind: string;
  label: string;
  status: StepStatus;
  error: string | null;
  /** Surowy klucz błędu (np. `channel_gone`): po nim UI rozróżnia stany, `error` jest do czytania. */
  error_key?: string | null;
  restore_bytes?: number | null; // cofnięcie usunięcia: instalacja z kopii (UI: „to potrwa”)
}

export type Outcome = 'ok' | 'still_active' | 'failed' | 'stopped';

export interface OrderResult {
  order: string;
  status: string;
  status_label: string;
  stopped: boolean;
  apps: { package: string; name: string; outcome: Outcome; errors: string[]; kinds: string[] }[];
  donate_reminder?: boolean; // brak w starszych nagraniach scenariuszy
  /** Zlecenie zmieniło zgody Firefoxa przez zdalne debugowanie: trzeba je potem wyłączyć. */
  firefox_debugging?: boolean;
}

export interface UndoDone {
  order: string;
  status: string;
  status_label: string;
  errors: string[];
  admin_not_restored: boolean;
  /** Witryny, które cofanie miało włączyć na telefonie, i ile z nich włączono (reszta: z historii). */
  sites_total: number;
  sites_restored: number;
  /** Włączone witryny; z `url` strona musi zapisać telefon od nowa (przycisk „otwórz”). */
  restored_sites: RestoredSite[];
  /** Cofnięto zgodę Firefoksa przez zdalne debugowanie: przypomnienie o jego wyłączeniu. */
  firefox_debugging: boolean;
  /** Przerwane zlecenia telefonu po cofnięciu: zlecenie bez kroków „w toku” znika z banera. */
  interrupted: string[];
}

/** Pozycja kolejki witryn w cofaniu (`undo:sites`): wiersz, który otworzy ekran na telefonie. */
export interface UndoSite {
  action_id: number;
  package: string;
  browser: string;
  /** Host witryny; null — wspólny kanał wszystkich witryn przeglądarki. */
  site: string | null;
}

export interface RestoredSite extends UndoSite {
  url: string | null;
}

export interface HistoryAction {
  id: number;
  package: string;
  level: string;
  level_label: string;
  kind: string;
  step_label: string;
  status: string;
  status_label: string;
  error: string | null;
  /** Kanał nie do przywrócenia (`channel_gone`): gdzie na telefonie samemu włączyć powiadomienia; null — nie dotyczy. */
  manual_undo?: string | null;
  /** Adres strony kanału po udanym cofnięciu (otwiera ją `open_site`); null — nie dotyczy. */
  site_url?: string | null;
}

export interface HistoryOrder {
  id: number;
  number: string;
  created_at: string;
  status: string;
  status_label: string;
  client: string | null;
  model: string | null;
  interrupted: boolean;
  manual: boolean;
  actions: HistoryAction[];
  /** Nazwy i ikony z migawki zlecenia; brak przy zleceniach sprzed migawek. */
  apps?: Record<string, { name: string | null; icon: string | null }>;
  screenshots: number;
}

export interface HistoryView {
  serial: string | null;
  serials: string[];
  orders: HistoryOrder[];
  devices: { serial: string; name: string; model: string | null; image: string; imei?: string | null }[];
}

export interface ConsoleEntry {
  time: string;
  serial: string | null;
  command: string;
  status: string;
  duration: number;
  output: string;
  tag: string | null;
}

export interface Question {
  job_id: string;
  kind: 'user_timeout';
  package: string;
  name: string;
}

/** Krok, w którym program czeka na ruch serwisanta na telefonie. */
export interface UserWait {
  package: string;
  name: string;
  kind: 'admin' | 'channel';
  /** Tylko `channel` dla jednej witryny: host; brak przy kanale wspólnym całej przeglądarki. */
  site?: string;
  browser?: string;
  timeout: number;
  action_id: number;
}

export interface ServiceInfo {
  name: string | null;
  address: string | null;
  phone: string | null;
  logo: string | null;
  email: string | null;
  nip: string | null;
  website: string | null;
  technician: string | null;
  footer: string | null;
}

export interface ReportResult {
  order: string;
  html: string;
  pdf: string | null;
  /** Gdzie miał trafić PDF (folder z ustawień albo domyślny), także po błędzie; starsze mosty go nie wysyłają. */
  pdf_target?: string | null;
  error: 'no_browser' | 'timeout' | 'failed' | 'locked' | 'folder' | null;
  opened: string | null; // null: zapisany, ale nieotwarty (brak programu albo `open_skipped`)
  /** Otwieranie wyłączone w ustawieniach („Otwieraj protokół po utworzeniu”): to nie błąd. */
  open_skipped?: boolean;
}

export type MirrorState = 'starting' | 'running' | 'stopped' | 'failed';

export interface MirrorView {
  serial: string | null;
  state: MirrorState;
  reason?: string | null;
}

export interface ShotView {
  id: number;
  taken_at: string;
  caption: string;
  black: boolean;
  in_report: boolean;
  image: string | null;
}

export interface ShotsView {
  order: string;
  limit: number;
  items: ShotView[];
}

export type AdbSource = 'settings' | 'bundled' | 'path' | 'missing';

export interface ApiErrorBody {
  key: string;
  message: string;
  /** Rodzaj zadania (`job:error`), np. `restore` — wybiera tekst błędu wgrywania. */
  kind?: string;
  /** Lokalny raport błędu do wysłania (internal). */
  crash?: string;
  serial?: string;
  /** Nazwa telefonu (wrong_device), jak na ekranie historii. */
  device?: string;
  imei?: string | null;
  log?: string;
  /** Strona pobierania (update_launch_failed). */
  page?: string;
  /** Najstarsza wspierana wersja (retired). */
  min_supported?: string;
}

export interface ApiError {
  error: ApiErrorBody;
}

export type JobError = ApiErrorBody & { job_id: string; kind: string };

// --- eksplorator plików (app/explorer_present.py, app/explorer_api.py)

/** Miejsce w lewym panelu; `count` — liczba plików, dochodzi zdarzeniem `explorer:places` (null: nie policzono). */
export interface PlaceView {
  key: 'camera' | 'screenshots' | 'downloads' | 'whatsapp' | 'movies' | 'music' | 'documents' | 'all';
  path: string;
  count: number | null;
  icon: 'camera' | 'screenshot' | 'download' | 'chat' | 'film' | 'music' | 'document' | 'phone';
}

/** Pamięć telefonu (`explorer_storage`, zdarzenie `explorer:storage`): bajty całości i zajęte oraz podział zajętych. */
export interface StorageView {
  total: number;
  used: number;
  /** Wolne jak w planie wgrywania (`df`, kolumna Available). */
  free: number;
  groups: { photos: number; videos: number; whatsapp: number; other: number };
}

export type FileKind = 'image' | 'video' | 'audio' | 'text' | 'apk' | 'doc' | 'other';

/** Wpis folderu telefonu. Folder: `type` „other”, `ext` pusty. `label` — ludzka nazwa folderu aplikacji;
 *  `locked` — Android nie pozwala zajrzeć (np. `Android/data`). `thumb`/`url` — lokalny serwer mediów. */
export interface EntryView {
  name: string;
  path: string;
  kind: 'dir' | 'file';
  size: number;
  mtime: number;
  label: string | null;
  locked: boolean;
  type: FileKind;
  ext: string;
  thumb: string | null;
  url: string | null;
}

/** Metadane pliku z `explorer_meta`: EXIF / MediaStore dosłownie, plus `gps`, `width`, `height` (zdjęcia). */
export type EntryMeta = Record<string, unknown> & { size: number; mtime: number; path: string };

export interface CrumbView {
  label: string;
  path: string;
}

export interface ExplorerOpenView {
  device: PhoneCard;
  places: PlaceView[];
  /** Adres lokalnego serwera mediów (miniatury, podgląd). */
  media: string;
  sdk: number;
  /** Ile naszych plików tymczasowych z poprzednich otwarć usunięto z telefonu. */
  leftovers: number;
  /** „Ostatnio” tego telefonu (najnowszy pierwszy); foldery innych telefonów most zostawia u siebie. */
  recent: string[];
}

export interface ExplorerListView {
  path: string;
  crumbs: CrumbView[];
  entries: EntryView[];
  /** Pozycje pominięte przy odczycie (np. nieczytelne nazwy). */
  skipped: number;
  /** Cały folder bez dostępu (kłódka zamiast błędu). */
  locked: boolean;
  /** Liczby podfolderów policzone już w tej sesji; resztę przynosi `explorer:folders`. */
  folders?: Record<string, FolderStatsView>;
}

/** Liczba plików i rozmiar folderu razem z podfolderami (także ukrytymi plikami — jak kopia folderu).
 *  `partial` — część podfolderów bez dostępu; `approx` — rozmiar z bloków dysku (starszy Android).
 *  `failed` — nie udało się policzyć (np. limit czasu). */
export type FolderStatsView = { files: number; bytes: number; partial: boolean; approx: boolean } | { failed: true };

export type TaskStatus = 'queued' | 'running' | 'paused' | 'waiting' | 'done' | 'cancelled' | 'failed';

/** Zadanie kolejki kopiowania (`to_pc`) albo wgrywania (`to_phone`). */
export interface TaskView {
  id: string;
  kind: 'to_pc' | 'to_phone';
  status: TaskStatus;
  done_files: number;
  total_files: number;
  done_bytes: number;
  total_bytes: number;
  speed: number;
  eta_s: number | null;
  skipped: number;
  renamed: number;
  failed: { path: string; reason: 'denied' | 'size' | 'mismatch' | 'missing' | 'error' }[];
  verified: 'size' | 'hash' | 'mismatch' | null;
  dest: string;
  /** Pozycje, których plan nie mógł odczytać: nie zostały skopiowane. */
  omitted: number;
  /** Gdzie trafiły pliki na telefonie (`Pokaż` je zaznacza). */
  targets: string[];
}

export interface ExplorerProblem {
  key: 'no_space' | 'read_only' | 'fat32_big' | 'path_too_long' | 'denied';
  detail: Record<string, unknown>;
}

export type ExplorerStart = { task: string } | { problems: ExplorerProblem[] };

// --- przenoszenie danych: kopia starego telefonu (present.inventory_view / copy_view / backup_result_view)

export type TransferCategory = 'media' | 'downloads' | 'whatsapp';

export interface InventoryApp {
  package: string;
  label: string;
  verdict: Verdict;
  default_on: boolean;
  bytes: number | null; // base + splity APK; null = telefon nie dał odczytać
}

/** Rodzaj pliku eksportu: wizytówki .vcf, SMS Backup & Restore (`<smses>`, `<calls>`). */
export type ExportKind = 'contacts' | 'sms' | 'calls';

/** Część inwentarza z `transfer_exports_check`. */
export type ExportsCheck = Pick<InventoryView, 'contacts' | 'sms' | 'mms' | 'mms_bytes' | 'calls' | 'denied' | 'exports'>;

/** Plik eksportu znaleziony na telefonie (z `present.inventory_view`). `mtime`: czas lokalny ISO, sekundy
 *  (null — telefon podał czas spoza zakresu dat, np. ujemny);
 *  `count`: null, gdy plik jest większy niż odczytany nagłówek (liczba będzie znana po pobraniu). */
export interface ExportFileView {
  remote: string;
  name: string;
  size: number;
  mtime: string | null;
  count: number | null;
}

export interface InventoryView {
  /** null: telefon nie pozwolił odczytać (np. Xiaomi bez „Debugowanie USB (ustawienia zabezpieczeń)”). */
  contacts: number | null;
  sms: number | null;
  mms: number | null;
  mms_bytes: number;
  calls: number | null;
  categories: Record<TransferCategory, { files: number; bytes: number }>;
  /** Folder `""` to luźne pliki w głównym folderze telefonu. */
  others: { name: string; files: number; bytes: number }[];
  apps: InventoryApp[];
  /** Szkodliwe — nie kopiujemy ich APK. */
  skipped_apps: { package: string; label: string }[];
  whatsapp_backup: string | null;
  storage: { used: number; total: number } | null;
  free_pc: number;
  unreadable: number;
  /** Kategorie, których odczytu telefon odmówił (nie zwykły błąd). */
  denied: ExportKind[];
  /** Pliki eksportu dla kategorii, których telefon nie dał odczytać — najnowsze pierwsze. */
  exports: Partial<Record<ExportKind, ExportFileView[]>>;
}

/** Wybór wysyłany do `start_backup` (Selection z silnika). */
export interface TransferSelection {
  contacts: boolean;
  sms: boolean;
  mms: boolean;
  calls: boolean;
  categories: TransferCategory[];
  others: string[];
  apps: string[];
  /** Wybrany plik eksportu (rodzaj → `remote`); most bierze tylko rodzaje z włączoną flagą. */
  exports?: Partial<Record<ExportKind, string>>;
}

/** Plik eksportu zapisany w wyborze kopii (`copy.selection.exports`). `mtime`: sekundy od epoki. */
export interface StoredExport {
  kind: ExportKind;
  remote: string;
  size: number;
  mtime: number;
}

/** Wybór zapisany w kopii — pliki eksportu jako lista, nie jak w `start_backup`. */
export type StoredSelection = Partial<Omit<TransferSelection, 'exports'>> & { verify_hash?: boolean; exports?: StoredExport[] };

export interface CopyView {
  id: string;
  serial: string;
  model: string;
  manufacturer: string;
  client: string | null;
  created: string;
  expires: string;
  days_left: number;
  status: 'in_progress' | 'complete' | 'incomplete';
  bytes: number;
  counts: Record<string, number>;
  /** Notatka serwisanta (`set_transfer_note`); starsze mosty jej nie wysyłają. */
  note?: string | null;
  /** Numer ZS zlecenia przeniesienia (null: kopia bez zlecenia); starsze mosty go nie wysyłają. */
  order?: string | null;
  /** Wybór zapisany w kopii (pusty, gdy kopia jeszcze nie ruszyła); wznowienie zaczyna od niego. */
  selection?: StoredSelection;
  /** Wgrywania tej kopii na nowe telefony, najnowsze pierwsze; starsze mosty ich nie wysyłają. */
  restores?: CopyRestore[];
}

/** Stan wgrywania kopii na jeden telefon (`read_restores`). `resumable`: zostały pliki do wgrania. */
export interface CopyRestore {
  serial: string;
  /** IMEI telefonu docelowego (zapisany przy wgrywaniu albo z podłączonego telefonu); null — pokazujemy numer seryjny. */
  imei?: string | null;
  /** running | complete | incomplete | stopped albo klucz błędu (np. `phone_full`). */
  status: string;
  updated: string | null;
  resumable: boolean;
}

// --- przenoszenie danych: wgrywanie kopii na nowy telefon (present.restore_plan_view / restore_result_view)

export type UploadGroup = 'photos' | 'videos' | 'downloads' | 'whatsapp';

export interface UploadTotals {
  files: number;
  /** Do wgrania: bez plików „już są”, z APK według domyślnego wyboru (szkodliwe i podejrzane poza sumą). */
  bytes: number;
  exists: number;
  rename: number;
}

export interface RestoreApk {
  remote: string;
  name: string;
  /** `photos`… albo `other:<folder>`. */
  group: string;
  bytes: number;
  action: 'push' | 'exists' | 'rename';
  outcome: 'clean' | 'suspicious' | 'malicious' | 'unknown';
  level: 'installed' | 'ioc' | 'static' | 'none';
  default_on: boolean;
}

/** Powód, dla którego aplikacji z kopii nie da się zainstalować (`apps_plan_view.items[].skip`). */
export type AppSkip = 'installed' | 'too_old' | 'too_new' | 'no_abi' | 'incomplete';

export interface AppsPlanItem {
  package: string;
  /** Etykieta ze starego telefonu (albo nazwa pakietu). */
  name: string;
  bytes: number;
  /** `unknown`: kopia bez werdyktów. */
  verdict: Verdict | 'unknown';
  default_on: boolean;
  skip: AppSkip | null;
}

/** Aplikacje z kopii na ekranie wgrywania. `bytes`: suma instalowalnych pozycji (`skip` pusty);
 *  `block`: `xiaomi` — telefon blokuje instalację przez USB. */
export interface AppsPlanView {
  items: AppsPlanItem[];
  block: 'xiaomi' | null;
  bytes: number;
}

export interface AppsResultRow {
  package: string;
  /** Etykieta tylko do UI. */
  label: string;
  status: 'pending' | 'installed' | 'exists' | 'skipped' | 'failed';
  reason: string | null;
}

/** Wynik instalacji aplikacji (`apps_result_view`). `failed`/`skipped`/`codes`: liczby według powodu / kodu `INSTALL_FAILED_…`. */
export interface AppsResultView {
  selected: number;
  installed: number;
  exists: number;
  skipped: Record<string, number>;
  failed: Record<string, number>;
  codes: Record<string, number>;
  blocked: boolean;
  stopped: boolean;
  rows: AppsResultRow[];
  play_installer: boolean;
}

/** Postęp etapu „Aplikacje” (`transfer:apps_progress`). */
export interface AppsProgressView { stage: 'apps'; done: number; total: number; current: string }

/** Ramka WhatsApp w wyniku wgrywania: `app` — czy aplikacja jest na telefonie. */
export interface WhatsappView {
  files: boolean;
  app: 'installed' | 'pre_installed' | 'missing';
}

/** Zlecenie ZS przeniesienia danych w Historii (`transfer_order_view`). */
export interface TransferOrderView {
  number: string;
  client: string | null;
  created_at: string;
  source: { name: string | null; imei: string | null };
  target: { name: string | null; imei: string | null } | null;
  state: 'copy_ready' | 'restored' | 'restored_notes' | 'failed' | 'expired';
  notes: number;
  /** Kopia, która jeszcze jest (dni do usunięcia) albo `deleted_at` po jej usunięciu; null — brak kopii i daty. */
  copy: { id: string; days_left: number; deleted_at: string | null } | null;
  whatsapp_restored: boolean;
  counts: Record<string, number>;
}

export interface RestorePlanView {
  /** Grupa bez plików może nie przyjść. */
  groups: Partial<Record<UploadGroup, UploadTotals>>;
  /** Foldery „Inne” z kopii; `""` = luźne pliki w folderze głównym. */
  others: ({ name: string } & UploadTotals)[];
  apks: RestoreApk[];
  space: { free: number; total: number | null };
  reserve: number;
  /** Pliki kopii, których nie ma już na komputerze — nie zostaną wgrane. */
  missing: number;
}

/** Wybór wysyłany do `start_restore` (UploadChoice z silnika). */
export interface UploadChoiceView {
  /** `photos`… albo `other:<folder>`. */
  groups: string[];
  /** `remote` zaznaczonych podejrzanych APK. */
  apks_on: string[];
  verify_hash: boolean;
  /** Telefonia do wgrania (`sms` obejmuje MMS); brak = bez telefonii. */
  tel: TelKind[];
  /** Pakiety aplikacji z planu aplikacji do zainstalowania; brak = bez aplikacji. */
  apps: string[];
}

// --- przenoszenie danych: kontakty, wiadomości i połączenia (present.tel_plan_view / tel_result_view)

/** Wiersz wyboru telefonii na ekranie wgrywania; `sms` obejmuje MMS. */
export type TelKind = 'contacts' | 'sms' | 'calls';
/** Kategoria w planie i wyniku (silnik prowadzi MMS osobno). */
export type TelCategory = 'contacts' | 'sms' | 'mms' | 'calls';

export interface TelKindPlan {
  /** Ile rekordów trafi na telefon. */
  write: number;
  /** Ile już na nim jest (0, gdy telefon nie dał odczytać — patrz `readable`). */
  existing: number;
}

export interface TelContactsPlan extends TelKindPlan {
  /** Kontakty z kont synchronizowanych: przyjdą same po zalogowaniu (adres konta tylko na ekranie). */
  skipped_synced: { account: string; count: number }[];
  /** Kontakty z komunikatorów (WhatsApp, Telegram…): pominięte. */
  skipped_messenger: number;
}

/** Kategoria, której nie ma w kopii, to `null`. */
export interface TelPlanView {
  contacts: TelContactsPlan | null;
  sms: TelKindPlan | null;
  mms: TelKindPlan | null;
  calls: TelKindPlan | null;
  phone_has_contacts: boolean;
  readable: Partial<Record<TelKind, boolean>>;
}

/** Droga zapisu: pomocnik jako shell, aplikacja pomocnicza (rola SMS), plik do ręcznego importu. */
export type TelPath = 'app_process' | 'companion' | 'file' | 'none';

export interface TelKindResultView {
  written: number;
  existed: number;
  skipped_synced: number;
  skipped_messenger: number;
  failed: number;
  manual: number;
  path: TelPath;
  /** Zapisane, ale aplikacja Wiadomości może ich nie pokazywać — do sprawdzenia na telefonie. */
  visible_warning: boolean;
}

export interface TelCleanupView {
  role_ok: boolean;
  appop_ok: boolean;
  companion_removed: boolean;
  helper_removed: boolean;
  ok: boolean;
}

export interface TelResultView {
  kinds: Partial<Record<TelCategory, TelKindResultView>>;
  safety: Partial<Record<TelCategory, boolean>>;
  /** Pliki do ręcznego importu: sama nazwa pliku w `Pobranych`. */
  manual: { kind: TelCategory; name: string }[];
  cleanup: TelCleanupView;
  synced_accounts: { account: string; count: number }[];
  seconds: number;
  stopped: boolean;
  status: 'complete' | 'incomplete';
}

export interface TelProgressView {
  kind: TelCategory | 'safety';  // `safety`: kopia bezpieczeństwa nowego telefonu (done/total = 0)
  done: number;
  total: number;
  path: TelPath;
}

/** Prośba o stuknięcie na telefonie: nadanie roli SMS na czas wgrywania albo jej oddanie poprzedniej aplikacji. */
export type TapRequest = 'sms_role_grant' | 'sms_role_restore';

export interface RestoreProgressView {
  stage: 'plan' | 'files' | 'scan';
  done_files: number;
  total_files: number;
  done_bytes: number;
  total_bytes: number;
  current: string;
}

export interface RestoreResultView {
  status: 'complete' | 'incomplete' | 'stopped';
  target_serial: string;
  files_done: number;
  files_exists: number;
  /** Wgrane obok jako „(z kopii)”. */
  files_renamed: number;
  files_denied: number;
  files_failed: number;
  files_unselected: number;
  /** Ocenione jako szkodliwe — nigdy nie wgrywane. */
  apk_skipped: number;
  apk_suspicious_skipped: number;
  bytes: number;
  seconds: number;
  hashed: boolean;
  /** `skipped`: przebieg się nie skończył (skan zrobi wznowienie) — wtedy bez prośby o restart. */
  media_scan: 'done' | 'failed' | 'restart' | 'skipped';
  files_missing: number;
}

export type TransferStage = 'telephony' | 'files' | 'apps' | 'verify';

export interface TransferProgress {
  stage: TransferStage;
  done_files: number;
  total_files: number;
  done_bytes: number;
  total_bytes: number;
  current: string;
  /** Aplikacje już obsłużone (także nieudane) i wybrane; starsze mosty ich nie wysyłają. */
  done_apps?: number;
  total_apps?: number;
}

export interface TelephonyResult {
  status: 'ok' | 'unavailable' | 'failed';
  count: number;
  /** np. `addresses_missing:3,attachments_missing:1`, `export_changed`, `export_invalid`; starsze widoki go nie mają. */
  error?: string | null;
  /** Skąd dane: z telefonu albo z pliku eksportu; starsze widoki go nie mają. */
  source?: 'phone' | 'export';
}

export interface BackupResultView {
  status: 'complete' | 'incomplete' | 'stopped';
  copy_id: string;
  telephony: Record<string, TelephonyResult>;
  files_done: number;
  files_failed: number;
  apps_done: number;
  apps_failed: number;
  bytes: number;
  seconds: number;
}

type R<T> = Promise<T | ApiError>;

export interface CrashSummary { id: string; kind: 'error' | 'ui' | 'thread' | 'exit'; created: string; type: string; sent_id: string | null }
export interface CrashPreview { body: Record<string, unknown>; has_adb: boolean }

export interface WhoEntry { package: string; name: string }
export interface IncidentHit { mark: number; package: string; name: string; kind: 'overlay' | 'new_notification' | 'foreground'; over: string | null; over_name: string | null }
export interface IncidentDone { marks: number; hits: IncidentHit[]; error?: ApiErrorBody }
export interface WhoView { resumed: WhoEntry | null; overlays: WhoEntry[] | null; errors: string[] }

export interface Api {
  get_settings(): R<Settings>;
  save_settings(changes: Partial<Settings>): R<Settings>;
  accept_welcome(telemetry: boolean, packages: boolean): R<Settings>;
  set_telemetry(telemetry: boolean, packages: boolean): R<Settings>;
  telemetry_sample(): R<TelemetrySample>;
  open_privacy(): R<{ ok: boolean }>;
  open_donate(): R<{ ok: boolean }>;
  set_donate_reminders(on: boolean): R<Settings>;
  apk_cache(): R<CacheUsage>;
  clear_apk_cache(): R<CacheCleared>;
  list_devices(): R<DevicesPayload>;
  watch_devices(on: boolean): R<{ ok: boolean }>;
  start_scan(serial: string, client: string | null): R<{ job_id: string }>;
  deep_analyze(pkg: string): R<{ job_id: string }>;
  analyze_selected(pkgs: string[]): R<{ job_id: string }>;
  analyze_all(): R<{ job_id: string }>;
  stop_apk_to_manual(): R<{ ok: boolean }>;
  selection_eta(pkgs: string[]): R<EtaView>;
  start_incident(seconds: number): R<{ ok: boolean }>;
  mark_incident(): R<{ ok: boolean }>;
  rerender(): R<{ scan: ScanView | null }>;
  preview_plan(requests: Record<string, Level>, unlocked: string[], fixes: string[]): R<PlanView>;
  share_plan(requests: Record<string, Level>, unlocked: string[], shareId: string, fixes: string[]): R<{ share_id: string; code: string }>;
  recheck_site_notifications(whenDebugging?: boolean): R<{ check: DeviceCheck | null }>;
  cancel_share(shareId: string): R<{ ok: boolean }>;
  execute(requests: Record<string, Level>, unlocked: string[], consent: { code: string } | null, fixes: string[]): R<{ job_id: string }>;
  resume(order: string): R<{ job_id: string }>;
  undo(order: string, actionId: number | null, pkg: string | null): R<{ job_id: string }>;
  stop(jobId: string): R<{ ok: boolean }>;
  /** Ekran oczekującego kroku (kanał witryny, administrator) otwiera się na telefonie jeszcze raz. */
  reopen_screen(): R<{ ok: boolean }>;
  skip_site(): R<{ ok: boolean }>;
  open_site(number: string, action_id: number): R<{ ok: boolean }>;
  answer(jobId: string, value: string): R<{ ok: boolean }>;
  history(serial: string | null): R<HistoryView>;
  delete_order(order: string): R<{ deleted: string }>;
  adb_shell(command: string): R<{ ok: boolean; output: string }>;
  who_is_showing(): R<WhoView>;
  check_adb(path: string | null): R<{ ok: boolean; version: string | null; message: string; source: AdbSource; path: string | null }>;
  mirror_status(): R<MirrorView & { available: boolean }>;
  mirror_start(serial: string, name: string | null): R<MirrorView>;
  mirror_stop(): R<{ ok: boolean }>;
  screenshot(serial: string): R<{ shot: ShotView; count: number }>;
  close_order(serial: string): R<{ ok: boolean }>;
  screenshots(order: string): R<ShotsView>;
  set_screenshot_in_report(id: number, on: boolean): R<ShotView>;
  pick_folder(): R<{ path: string | null }>;
  report(order: string): R<ReportResult>;
  service(): R<ServiceInfo>;
  save_service(changes: Partial<ServiceInfo>): R<ServiceInfo>;
  pick_logo(): R<{ path: string | null }>;
  pick_adb(): R<{ path: string | null }>;
  update_state(): R<UpdateView>;
  dismiss_update(version: string): R<UpdateView>;
  install_update(): R<{ job_id: string } | { opened: boolean }>;
  capture_ui_error(message: string, stack: string | null, screen: string | null): R<{ crash: string | null }>;
  crash_reports(): R<{ reports: CrashSummary[]; startup: string[] }>;
  crash_preview(id: string, include_adb: boolean, comment: string): R<CrashPreview>;
  send_crash(id: string, include_adb: boolean, comment: string): R<{ sent_id: string }>;
  discard_crash(id: string): R<Record<string, never>>;
  quit(): R<{ ok: boolean; closing_after_step?: boolean }>;
  transfer_inventory(serial: string, client: string | null): R<{ job_id: string }>;
  transfer_whatsapp(): R<{ whatsapp_backup: string | null }>;
  /** Ponowny odczyt telefonu (np. po eksporcie kontaktów do pliku) — wynik jak `transfer_inventory`. */
  transfer_rescan(): R<{ job_id: string }>;
  /** Tani odczyt pod automatyczne sprawdzanie (bez zadania): liczby z providerów i pliki eksportu. */
  transfer_exports_check(): R<ExportsCheck>;
  start_backup(selection: TransferSelection): R<{ job_id: string }>;
  transfers(): R<{ orders: TransferOrderView[]; copies: CopyView[] }>;
  /** Czy telefon z ostatniego planu wciąż blokuje instalację przez USB (Xiaomi); null — nieznane. */
  install_check(): R<{ blocked: boolean | null }>;
  /** Dokończenie instalacji aplikacji pominiętych z powodu blokady (po odblokowaniu telefonu). */
  install_remaining_apps(order: string): R<{ job_id: string }>;
  /** Serwisant potwierdza (albo cofa), że WhatsApp przywrócono z kopii na telefonie klienta. */
  set_whatsapp_restored(order: string, on: boolean): R<{ order: string; whatsapp_restored: boolean }>;
  extend_transfer(copyId: string): R<{ copy: CopyView }>;
  /** Pusta albo null usuwa notatkę; za długa (>2000 znaków): `bad_request`. */
  set_transfer_note(copyId: string, note: string | null): R<{ copy: CopyView }>;
  delete_transfer(copyId: string): R<{ deleted: string }>;
  restore_plan(copyId: string, serial: string): R<{ job_id: string }>;
  start_restore(choice: UploadChoiceView): R<{ job_id: string }>;
  /** „Pomiń” przy prośbie o rolę SMS: wiadomości idą do pliku. Odmowa: `restore_required` (oddania roli
   *  nie wolno pominąć) albo `no_tap` (nic nie czeka). */
  skip_tap(): R<Record<string, never>>;
  /** Eksplorator plików: trzyma blokadę telefonu do `explorer_close`; zajęty telefon → `explorer_busy`. */
  explorer_open(serial: string): R<ExplorerOpenView>;
  explorer_close(): R<Record<string, never>>;
  explorer_storage(): R<StorageView>;
  explorer_list(path: string): R<ExplorerListView>;
  explorer_meta(path: string): R<{ meta: EntryMeta }>;
  explorer_text(path: string, more: boolean): R<{ text: string; encoding: string; truncated: boolean }>;
  explorer_text_head(path: string): R<{ text: string; truncated: boolean }>;
  /** Arkusz (XLSX/XLSM/XLS/CSV/TSV): wszystkie arkusze jako tekst komórek albo `problem`, gdy się nie da. */
  explorer_sheet(path: string): R<SheetBookView | SheetProblem>;
  /** Początek pierwszego arkusza do dymku, z nazwami wszystkich arkuszy. */
  explorer_sheet_head(path: string): R<SheetHeadView | SheetProblem>;
  explorer_mkdir(parent: string, name: string): R<{ path: string }>;
  explorer_new_text(parent: string, name: string, text: string): R<{ path: string }>;
  explorer_open_map(lat: number, lon: number): R<Record<string, never>>;
  explorer_copy(paths: string[], dest: string | null, verifyHash: boolean, exclude?: string[]): R<ExplorerStart>;
  explorer_upload(paths: string[], remoteDir: string, verifyHash: boolean): R<ExplorerStart>;
  explorer_retry(taskId: string): R<{ task: string | null }>;
  explorer_pick_dest(): R<{ path: string | null }>;
  explorer_clear_recents(): R<{ phones: number }>;
  explorer_pick_upload(kind: 'files' | 'folder'): R<{ paths: string[] }>;
  explorer_clipboard(): R<{ paths: string[] }>;
  explorer_tasks(): R<{ tasks: TaskView[] }>;
  explorer_pause(taskId: string): R<Record<string, never>>;
  explorer_resume(taskId: string): R<Record<string, never>>;
  explorer_cancel(taskId: string): R<Record<string, never>>;
  explorer_open_folder(path: string): R<Record<string, never>>;
}

export interface EventMap {
  devices: DevicesPayload;
  'scan:stage': { stage: string };
  'scan:device': { device: PhoneCard };
  'scan:done': { scan: ScanView; interrupted: string[]; client: string | null };
  'apk:progress': { done: number; total: number; package: string; eta_s: number | null; job_id?: string };
  'apk:estimate': ApkEstimate & { job_id?: string; scope: 'all' | 'part' };  // part: zaznaczone albo jedna aplikacja
  'apk:question': ApkQuestion;
  'apk:done': { scan: ScanView; job_id?: string };
  'apk:manual': { scan: ScanView; job_id?: string };
  'apk:stopped': { job_id?: string };
  'exec:order': { order: string; plan: PlanView | null };
  'exec:step': StepEvent;
  'exec:user_wait': UserWait;
  'exec:user_done': { package: string; status: string };
  'exec:question': Question;
  'exec:verify': Record<string, never>;
  'exec:stopped': { order: string };
  'exec:done': OrderResult;
  'exec:disconnected': { order: string };
  'undo:step': StepEvent;
  'undo:sites': { order: string; sites: UndoSite[] };
  'undo:done': UndoDone;
  'adb:command': ConsoleEntry;
  'job:error': JobError;
  'share:ready': ShareReady;
  'share:failed': ShareFailed;
  'job:end': { job_id: string; kind: string };
  'app:close_requested': { kind: string };
  'update:state': UpdateView;
  'telemetry:deleted': Record<string, never>;
  'update:progress': { done: number; total: number | null };
  'mirror:state': MirrorView;
  'mirror:warning': { serial: string; code: 'control_blocked' | 'stay_awake_blocked' };
  'incident:state': { recording: boolean; seconds: number };
  'incident:done': IncidentDone;
  'transfer:inventory': { inventory: InventoryView; resumable: CopyView | null; client: string | null };
  'transfer:progress': TransferProgress;
  'transfer:waiting': Record<string, never>;
  /** Kopia założona albo wznowiona — zaraz po starcie, przed pierwszym `transfer:progress`. */
  'transfer:copy': { copy: CopyView };
  'transfer:done': { result: BackupResultView; copy: CopyView };
  'transfer:restore_plan': { plan: RestorePlanView; tel: TelPlanView | null; apps: AppsPlanView; order: string | null;
    copy: CopyView; resumable: boolean; same_phone_recent: boolean };
  'transfer:restore_progress': RestoreProgressView;
  'transfer:tel_progress': TelProgressView;
  'transfer:apps_progress': AppsProgressView;
  /** Koniec dokończenia instalacji (`install_remaining_apps`): wynik zastępuje `apps` w zleceniu. */
  'transfer:apps_done': { order: string; apps: AppsResultView };
  /** `request` null: prośba załatwiona. `package`: poprzednia domyślna aplikacja SMS (null — nieznana). */
  'transfer:tap': { request: TapRequest | null; package: string | null };
  /** Start przywracania ustawień telefonu `serial` po przerwanym wgrywaniu (także ponowienia w tle). */
  'transfer:cleanup_started': { serial: string };
  /** Koniec przywracania ustawień telefonu; nieudane most ponawia w tle (najwyżej 3 próby na podłączenie). */
  'transfer:cleanup_done': { ok: boolean; serial: string };
  /** `tel`: null dla samych plików albo po błędzie telefonii (`tel_error` — klucz błędu). */
  'transfer:restore_done': { result: RestoreResultView; copy: CopyView; tel?: TelResultView | null; tel_error?: string | null;
    apps: AppsResultView | null; apps_error?: string | null; order: string | null; whatsapp: WhatsappView | null };
  /** Eksplorator: liczby plików Miejsc liczone w tle (po każdym miejscu cała lista). */
  'explorer:places': { places: PlaceView[] };
  /** Telefon eksploratora zniknął z listy — most czeka na niego (kolejka stoi). */
  'explorer:offline': { serial: string };
  /** Ten sam telefon wrócił — UI odświeża bieżący folder. */
  'explorer:online': { serial: string };
  /** Most zamknął eksplorator: podłączono inny telefon albo otwarto eksplorator innego telefonu. */
  'explorer:closed': { serial: string; reason: 'other_phone' | 'switched' };
  /** Pamięć telefonu po zadaniu wgrywania (poziom „cieczy” w Miejscach rośnie na żywo). */
  'explorer:storage': StorageView;
  /** Liczby folderów z liczenia w tle; `null` — folder do policzenia od nowa (coś do niego wgrano). */
  'explorer:folders': { serial: string; folders: Record<string, FolderStatsView | null> };
  'explorer:task': { task: TaskView };
  /** Pliki upuszczone z Eksploratora Windows (liczba plików i bajty z folderami). */
  'explorer:drop': { paths: string[]; count: number; bytes: number };
}

export type EventName = keyof EventMap;

/** Arkusz w podglądzie: wiersze jako tekst komórek (puste na końcu wiersza obcięte). CSV ma jeden arkusz bez nazwy. */
export interface SheetView {
  name: string;
  rows: string[][];
  truncated: boolean;
  hidden: boolean;
}

export interface SheetBookView {
  sheets: SheetView[];
  delimiter: string | null;
  encoding: string | null;
}

export interface SheetHeadView {
  names: string[];
  rows: string[][];
  truncated: boolean;
}

/** Arkusza nie pokażemy: za duży, z hasłem albo nie do odczytania (np. „.xls” będący stroną HTML). */
export interface SheetProblem {
  problem: 'too_big' | 'encrypted' | 'unreadable';
}
