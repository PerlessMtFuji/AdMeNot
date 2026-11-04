"""Most GUI <-> silnik (spec §3.2): metody dla `window.pywebview.api`, zdarzenia `admenot:*`.

pywebview wystawia do JS publiczne metody i atrybuty — cały stan trzymamy w polach `_…`.
Każda publiczna metoda zwraca słownik JSON; błąd to `{"error": {"key", "message", …}}`.
Długie operacje (skan, analiza APK, wykonanie, wznowienie, cofnięcie) idą przez `JobRunner`
i od razu zwracają `{"job_id"}`; postęp przychodzi zdarzeniami.
Protokół i dane serwisu nie dotykają telefonu, więc idą bez JobRunner (pywebview woła każdą metodę w osobnym wątku).
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Iterator
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from admenot import __version__
from admenot.app import crash, telemetry
from admenot.app.errors import AppError, bridge, error_payload, log_exception, report_error
from admenot.app.events import Emitter
from admenot.app.explorer_api import ExplorerMixin, MediaFactory
from admenot.app.jobs import Job, JobRunner, Stopped
from admenot.app.present import (
    app_name,
    backup_result_view,
    browser_names,
    copy_view,
    device_card,
    device_checks_view,
    device_identity,
    estimate_view,
    eta_view,
    fix_texts,
    history_view,
    inventory_view,
    plan_view,
    restore_plan_view,
    restore_result_view,
    result_view,
    scan_view,
    step_view,
    tel_plan_view,
    tel_result_view,
)
from admenot.app.telemetry_events import (
    repair_event,
    sample,
    scan_event,
    transfer_backup_event,
    transfer_restore_event,
    undo_event,
    undo_targets,
)
from admenot.app.updates import UpdateService, update_view
from admenot.app.watcher import DeviceWatcher
from admenot.engine import donate, retention, share, welcome
from admenot.engine.actions.errors import ActionError
from admenot.engine.actions.executor import ExecOptions, run_order
from admenot.engine.actions.executor import resume as resume_steps
from admenot.engine.actions.steps import Step, site_url
from admenot.engine.actions.steps import open_site as open_site_on_phone
from admenot.engine.adb.devices import list_devices
from admenot.engine.adb.sessionlog import SessionLogAdb, session_log_path
from admenot.engine.adb.transport import AdbError, AdbTransport, RealAdb
from admenot.engine.apk.cache import GB, CacheUsage, Estimate, clear_cache, disk_total, usage
from admenot.engine.apk.fetch import default_cache_dir
from admenot.engine.apk.providers import ApkProvider, CachePolicy, DeviceApkProvider, ManualMode
from admenot.engine.apk.timing import (
    Eta,
    Speeds,
    estimate_eta,
    learn,
    live_eta,
    load_speeds,
    save_speeds,
)
from admenot.engine.applabels import LabelFetch, PhoneLabel, list_apps
from admenot.engine.clientpaths import client_paths
from admenot.engine.device.identity import same_device
from admenot.engine.device.info import DeviceInfo, read_device_info
from admenot.engine.device_checks import (
    SITE_NOTIFICATIONS,
    debugging_appeared,
    read_site_notifications,
)
from admenot.engine.foreground import read_foreground
from admenot.engine.incident import attribute, load_incident, record, save_incident
from admenot.engine.journal.db import (
    MAX_REPORT_SCREENSHOTS,
    Journal,
    Order,
    Screenshot,
    ScreenshotLimit,
)
from admenot.engine.mirror import Mirror, MirrorUnavailable
from admenot.engine.oplock import DeviceBusy, device_lock
from admenot.engine.paths import incident_path, journal_path, logs_dir, screenshot_files
from admenot.engine.phones.provider import PhoneMatch, PhoneProvider
from admenot.engine.report.files import UnknownOrder, write_report
from admenot.engine.report.render import data_uri
from admenot.engine.screenshot import delete_shots, take_screenshot
from admenot.engine.session import ScanReport, analyze_apks, apply_phone_labels, run_scan
from admenot.engine.settings import (
    LogoError,
    ServiceInfo,
    SettingsTooNew,
    archive_dir_ok,
    check_logo,
    effective_lang,
    load_service,
    load_settings,
    save_service,
    save_settings,
)
from admenot.engine.texts import (
    browser_name,
    error_text,
    fix_step_texts,
    order_status_label,
    screenshot_caption,
)
from admenot.engine.tools import resolve_adb
from admenot.engine.transfer import store
from admenot.engine.transfer.backup import (
    BackupError,
    BackupResult,
    ExportChoice,
    Progress,
    Selection,
    run_backup,
)
from admenot.engine.transfer.exports import EXPORT_KINDS
from admenot.engine.transfer.guard import AppendOnlyAdb, ReadOnlyAdb, TelPlanReadAdb
from admenot.engine.transfer.inventory import (
    FILE_CATEGORIES,
    Inventory,
    build_inventory,
    refresh_inventory,
    whatsapp_backup_time,
)
from admenot.engine.transfer.phonesetup import (
    Changes,
    cleanup,
    device_changes,
    open_changes,
    pending_cleanup,
    telephony_adb,
)
from admenot.engine.transfer.puller import Puller, RealPuller
from admenot.engine.transfer.pusher import Pusher, RealPusher
from admenot.engine.transfer.restore import (
    STREAMS,
    TEL_KINDS,
    RestoreError,
    RestoreProgress,
    RestoreResult,
    UploadChoice,
    engine_tel_kinds,
    run_restore,
    settle_finished,
    tel_records_to_write,
)
from admenot.engine.transfer.restore_plan import UPLOAD_GROUPS, RestorePlan, build_plan
from admenot.engine.transfer.restore_state import (
    RestoreState,
    read_restores,
    restore_state_path,
)
from admenot.engine.transfer.restore_tel import TelProgress, TelResult, run_tel_restore
from admenot.engine.transfer.telephony import TEL_CATEGORIES
from admenot.engine.transfer.telephony import Stopped as TransferStopped
from admenot.engine.transfer.telplan import TelPlan, build_tel_plan
from admenot.engine.workflow import (
    OrderInterrupted,
    OrderResult,
    Runner,
    clear_cache_after_repair,
    execute_order,
    plan_order,
    start,
    targeted_actions,
    undo_order,
)
from admenot.net import client, installer, update
from admenot.net.client import BackendError

HostFactory = Callable[[str | None], AdbTransport]
ApkFactory = Callable[..., ApkProvider]
PullerFactory = Callable[[str | None, str, SessionLogAdb], Puller]
PusherFactory = Callable[[str | None, str, SessionLogAdb], Pusher]

ADMIN_TIMEOUT = 180.0
# Dwa scrcpy naraz wgrywają ten sam /data/local/tmp/scrcpy-server.jar: nazwy aplikacji czekają,
# aż podgląd wystartuje, a start podglądu — aż skończy się odczyt nazw (zwykle ~3 s).
SCRCPY_TURN_WAIT_S = 10.0
DEFAULT_WORKERS = 2  # równoległość DeviceApkProvider (apk/providers.py)
ORDER_KINDS = frozenset({"exec", "resume", "undo"})
INCIDENT_MAX_S = 600.0  # nagranie incydentu: najwyżej 10 min
INCIDENT_INTERVAL_S = 2.0
CONSOLE_TIMEOUT = 30.0
QUIT_WAIT = 30.0
SHARE_RETRY_S = 15.0  # ponawianie wysyłki planu bez sieci (spec plan-qr §5.3)
SHARE_RETRY_WINDOW_S = 120.0
_SHARE_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
SHOWN_MAX = 200  # pamiętane kody kontrolne pokazane klientom w tej sesji; najstarsze odpadają
TRANSFER_PURGE_S = 24 * 3600.0  # kopie danych po terminie: sprawdzane też w trakcie pracy okna
TRANSFER_PROGRESS_S = 0.5  # dławienie zdarzeń `transfer:progress`
TRANSFER_KINDS = frozenset({"transfer_scan", "backup", "restore_plan", "restore", "phone_cleanup"})
# zadania, które czytają kopię z dysku (sprzątanie: stany wgrywania w katalogach kopii)
RESTORE_KINDS = frozenset({"restore_plan", "restore", "phone_cleanup"})
# Odstęp przed kolejnymi automatycznymi próbami sprzątania telefonu (s) w jednym podłączeniu: pierwsza od
# razu, druga po 10 s, trzecia po 30 s od nieudanej; potem bez ponowień do ponownego podłączenia.
CLEANUP_BACKOFF = (0.0, 10.0, 30.0)
SAME_PHONE_RECENT = timedelta(hours=24)  # wgrywanie na telefon, z którego jest świeża kopia: ostrzeżenie


def _real_host(adb_path: str | None) -> AdbTransport:
    return RealAdb(adb_path=adb_path)


def _adb_path(adb_path: str | None) -> str:
    path = resolve_adb(adb_path).path
    if path is None:
        raise AdbError("adb_missing", "adb")
    return path


def _real_puller(adb_path: str | None, serial: str, log: SessionLogAdb) -> Puller:
    return RealPuller(_adb_path(adb_path), serial, log)


def _real_pusher(adb_path: str | None, serial: str, log: SessionLogAdb) -> Pusher:
    return RealPusher(_adb_path(adb_path), serial, log)


def _startfile(path: Path) -> None:
    os.startfile(path)  # type: ignore[attr-defined]  # tylko Windows


SERVICE_KEYS = ("name", "address", "phone", "logo")


def _service_view(info: ServiceInfo) -> dict[str, Any]:
    return {"name": info.name, "address": info.address, "phone": info.phone,
            "logo": str(info.logo) if info.logo else None}


def _fixes(value: Any) -> tuple[str, ...]:
    """Wybrane poprawki „Stanu telefonu”: lista napisów (identyfikatory), brak = żadnej."""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise AppError("bad_request", "fixes")
    return tuple(value)


def _export_choices(value: Any, flags: dict[str, Any], inventory: Inventory) -> tuple[ExportChoice, ...]:
    """Pliki eksportu z ekranu kopii (rodzaj → ścieżka). Ścieżka musi być kandydatem z inwentarza,
    a flaga rodzaju włączona; rozmiar i mtime bierzemy z inwentarza, nie od UI."""
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise AppError("bad_request", "selection")
    chosen = []
    for kind, remote in value.items():
        if kind not in EXPORT_KINDS or not isinstance(remote, str) or flags[kind] is not True:
            raise AppError("bad_request", "selection")
        file = next((e for e in inventory.exports.get(kind, []) if e.remote == remote), None)
        if file is None:
            raise AppError("bad_request", "selection")
        chosen.append(ExportChoice(file.kind, file.remote, file.size, file.mtime))
    return tuple(chosen)


def _selection(value: Any, inventory: Inventory) -> Selection:
    """Wybór z ekranu kopii: flagi telefonii, listy kategorii / folderów / pakietów, pliki eksportu."""
    if not isinstance(value, dict):
        raise AppError("bad_request", "selection")
    flags = {k: value.get(k) for k in ("contacts", "sms", "mms", "calls")}
    verify = value.get("verify_hash", False)
    if not all(isinstance(v, bool) for v in (*flags.values(), verify)):
        raise AppError("bad_request", "selection")
    lists: dict[str, frozenset[str]] = {}
    for key in ("categories", "others", "apps"):
        items = value.get(key)
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            raise AppError("bad_request", "selection")
        lists[key] = frozenset(items)
    if not lists["categories"] <= set(FILE_CATEGORIES):
        raise AppError("bad_request", "selection")
    exports = _export_choices(value.get("exports"), flags, inventory)
    if any(c.kind == "sms" for c in exports):
        flags["mms"] = False  # MMS idą przez providera, a ten odmówił — z pliku XML ich nie ma
    return Selection(**flags, **lists, verify_hash=verify, exports=exports)


def _upload_choice(value: Any, plan: RestorePlan) -> UploadChoice:
    """Wybór z ekranu wgrywania: grupy (`UPLOAD_GROUPS` albo `other:<folder>` z planu), zaznaczone
    podejrzane APK (tylko pliki APK z planu), sumy SHA-256 i telefonia (`tel` ⊆ `TEL_KINDS`, brak =
    bez telefonii; `sms` obejmuje MMS). Nieznana grupa, plik albo kategoria → odmowa."""
    if not isinstance(value, dict):
        raise AppError("bad_request", "choice")
    lists: dict[str, frozenset[str]] = {}
    for key in ("groups", "apks_on", "tel"):
        items = value.get(key, [] if key == "tel" else None)
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            raise AppError("bad_request", "choice")
        lists[key] = frozenset(items)
    verify = value.get("verify_hash", False)
    if not isinstance(verify, bool):
        raise AppError("bad_request", "choice")
    known = set(UPLOAD_GROUPS) | {g for g in plan.groups if g.startswith("other:")}
    apks = {f.remote for f in plan.files if f.apk is not None}
    if not lists["groups"] <= known or not lists["apks_on"] <= apks or not lists["tel"] <= TEL_KINDS:
        raise AppError("bad_request", "choice")
    return UploadChoice(lists["groups"], lists["apks_on"], verify, lists["tel"])


@contextlib.contextmanager
def _transfer_errors(kind: str) -> Iterator[None]:
    """Błędy zadań kopii danych. Znane przechodzą jak zwykle (`BackupError` → `transfer_<klucz>`);
    każdy inny to `transfer_failed`: pełny wyjątek tylko w lokalnym logu, a raport błędu dostaje typ
    i komunikat po `redact` (ścieżki z telefonu i z kopii zwinięte) — nazwy plików klienta nie
    wychodzą z komputera."""
    try:
        yield
    except (BackupError, RestoreError) as exc:
        raise AppError(f"transfer_{exc.key}") from None
    except (AppError, AdbError, DeviceBusy, Stopped):
        raise
    except Exception as exc:  # noqa: BLE001 — każdy inny błąd kopii pod jednym kluczem
        extra: dict[str, Any] = {}
        try:
            extra["log"] = str(log_exception(exc, scrub=client_paths))  # bez nazw plików klienta
        except OSError:
            extra["log_failed"] = True
        crash_id = crash.capture(exc, message=f"{type(exc).__name__}: {exc}", context={"job": kind})
        if crash_id:
            extra["crash"] = crash_id
        raise AppError("transfer_failed", type(exc).__name__, **extra) from None


_api = bridge


class Api(ExplorerMixin):
    def __init__(
        self,
        emitter: Emitter,
        host_factory: HostFactory = _real_host,
        provider: PhoneProvider | None = None,
        apk_factory: ApkFactory | None = DeviceApkProvider,
        *,
        sync_jobs: bool = False,
        admin_timeout: float = ADMIN_TIMEOUT,
        poll_interval: float = 1.0,
        now: Callable[[], datetime] = datetime.now,
        open_file: Callable[[Path], None] = _startfile,
        mirror_factory: Callable[..., Mirror] = Mirror,
        app_labels: Callable[..., dict[str, PhoneLabel]] = list_apps,
        update_fetch: Callable[[], update.Manifest] = update.fetch,
        update_download: Callable[..., Path] = installer.download,
        launch_setup: Callable[[Path], object] = installer.launch,
        open_url: Callable[[str], object] = webbrowser.open,
        frozen: bool | None = None,
        share_upload: Callable[[bytes], tuple[str, str]] = client.create_share,
        share_retry_s: float = SHARE_RETRY_S,
        share_retry_window_s: float = SHARE_RETRY_WINDOW_S,
        puller_factory: PullerFactory = _real_puller,
        pusher_factory: PusherFactory = _real_pusher,
        transfer_purge_s: float | None = TRANSFER_PURGE_S,
        explorer_media: MediaFactory | None = None,
        explorer_temp: Path | None = None,
        explorer_clipboard: Callable[[], list[str]] | None = None,
    ) -> None:
        self._emitter = emitter
        self._host_factory = host_factory
        self._provider = provider or PhoneProvider.default()
        self._apk_factory = apk_factory
        self._app_labels = app_labels
        self._labels: LabelFetch | None = None  # odczyt nazw bieżącego skanu
        self._jobs = JobRunner(emitter, sync=sync_jobs)
        # Porzucenie analizy APK i zapis jej wyniku wykluczają się: porzucone zadanie nie podmieni
        # raportu nowego skanu (audyt 2026-10-11, BUG-10).
        self._apk_commit = threading.Lock()
        self._reopen = threading.Event()  # „Otwórz ponownie na telefonie” (`reopen_screen`)
        self._skip = threading.Event()  # „Pomiń tę witrynę” w cofaniu (`skip_site`)
        # Rośnie przy każdym pokazanym planie: odczyt witryn trwający w tym czasie nie podmienia
        # kontroli, z których zlecenie zostanie wykonane (pokazano plan ze starych).
        self._plans_shown = 0
        self._admin_timeout = admin_timeout
        self._poll_interval = poll_interval
        self._now = now
        self._settings = load_settings()
        self._lang = effective_lang(self._settings)
        self._host = host_factory(self._settings.adb_path)
        self._watcher = DeviceWatcher(self._device_list, lambda p: self._emit("devices", p),
                                      paused=lambda: self._jobs.current() is not None)
        self._adb: SessionLogAdb | None = None
        self._serial: str | None = None
        self._client: str | None = None
        self._scan_session: str | None = None  # łączy skan z naprawą w statystykach
        self._report: ScanReport | None = None
        self._estimate: Estimate | None = None  # ostatni pełny szacunek: czas analizy zaznaczonych
        self._eta: Eta | None = None  # szacunek pokazany przy wyborze trybu (telemetria)
        self._to_manual: str | None = None  # zadanie APK przerwane „Przerwij i szukaj ręcznie”
        self._match: PhoneMatch | None = None
        self._pick_folder_fn: Callable[[], str | None] | None = None
        self._close_fn: Callable[[], None] | None = None
        self._quitting = False
        self._open_file = open_file
        self._report_lock = threading.Lock()
        self._sync = sync_jobs
        self._incident_record = record  # podmieniane w testach
        self._incident_mark = threading.Event()
        self._incident_active = False
        self._incident_lock = threading.Lock()
        self._pick_file_fn: Callable[[], str | None] | None = None
        self._open_order: dict[str, int] = {}  # telefon → zlecenie, do którego idą nowe zrzuty
        self._identities: dict[str, tuple[str | None, str | None, str | None, str | None]] = {}  # → (nazwa, IMEI, obrazek, Android)
        self._pending: dict[str, list[int]] = {}  # telefon → zrzuty czekające na zlecenie
        self._shots_lock = threading.Lock()  # chroni _open_order/_pending; nigdy pod adb/screencap
        self._share_upload = share_upload
        self._share_retry_s = share_retry_s
        self._share_retry_window_s = share_retry_window_s
        self._share_lock = threading.Lock()
        self._share_cancel: tuple[str, threading.Event] | None = None  # (share_id, sygnał przerwania)
        self._shown: dict[str, datetime] = {}  # kod kontrolny → kiedy pokazany klientowi
        self._puller_factory = puller_factory
        # Ostatni inwentarz kopii danych: (telefon, inwentarz, klient) — z niego startuje kopia.
        self._transfer: tuple[DeviceInfo, Inventory, str | None] | None = None
        self._backup_serial: str | None = None  # telefon, którego kopia właśnie trwa
        self._pusher_factory = pusher_factory
        # Ostatni plan wgrywania: (nowy telefon, kopia, plan plików, plan telefonii) — z niego startuje
        # wgrywanie.
        self._restore: tuple[DeviceInfo, store.CopyDir, RestorePlan, TelPlan] | None = None
        self._restore_copy_id: str | None = None  # kopia czytana przez plan albo wgrywanie
        # Prośba o stuknięcie na telefonie (`transfer:tap`): „sms_role_grant” | „sms_role_restore” | None.
        self._tap_request: str | None = None
        self._skip_tap = threading.Event()  # „Pomiń” przy nadaniu roli SMS (`skip_tap`)
        # Telefony sprawdzone pod kątem zmian do odwrócenia w tym podłączeniu (sprzątanie przy podłączeniu).
        self._cleaned: set[str] = set()
        # Nieudane sprzątanie w tym podłączeniu: telefon → (liczba nieudanych prób, najwcześniej następna
        # automatyczna próba wg `_clock`). Po `len(CLEANUP_BACKOFF)` próbach koniec ponowień do odłączenia.
        self._cleanup_tries: dict[str, tuple[int, float]] = {}
        self._clock = time.monotonic  # podmieniane w testach (odstępy ponowień sprzątania)
        self._check_failed: set[str] = set()  # nieudany odczyt zmian telefonu już zalogowany (to podłączenie)
        # Sprawdzenie i start sprzątania: wątek obserwatora telefonów, `list_devices` i wejścia zadań naraz
        # (RLock: zadanie synchroniczne w testach woła wejścia z wnętrza sprzątania).
        self._cleanup_lock = threading.RLock()
        self._purge_stop = threading.Event()
        # Eksplorator plików (`ExplorerMixin`): sesja, serwer mediów (podmieniany w testach), `%TEMP%`.
        self._explorer_setup(explorer_media, explorer_temp, explorer_clipboard)
        self._clean_screenshots()
        self._purge_old_data()
        # Zegar dobowy: okno bywa otwarte dniami, a kopie po 7 dniach mają zniknąć. Testy
        # (`sync_jobs`) go nie uruchamiają — każdy `Api` zostawiałby wątek do końca procesu.
        if transfer_purge_s and not sync_jobs:
            threading.Thread(target=self._purge_loop, args=(transfer_purge_s,), daemon=True,
                             name="admenot-transfer-purge").start()
        self._mirror = mirror_factory(
            lambda view: self._emit("mirror:state", view),
            lambda view: self._emit("mirror:warning", view),
            self._mirror_line,
            adb=lambda: resolve_adb(self._settings.adb_path).path)
        self._frozen = getattr(sys, "frozen", False) if frozen is None else frozen
        self._update_download = update_download
        self._launch_setup = launch_setup
        self._open_url = open_url
        self._updated_to = self._note_version()
        self._updates = UpdateService(lambda: self._emit("update:state", self._update_view()),
                                      lambda: self._settings.check_updates, fetch=update_fetch)

    # --- pomocnicze (nie są wystawiane do JS) -----------------------------------------------

    def _utc(self) -> datetime:
        return datetime.now(UTC)

    def _emit(self, name: str, detail: Any = None) -> None:
        self._emitter.emit(name, detail)

    def _journal(self) -> Journal:
        return Journal(journal_path(), now=self._now)

    def _session(self, serial: str) -> SessionLogAdb:
        return SessionLogAdb(self._host.with_serial(serial),
                             session_log_path(logs_dir(), self._now()), now=self._now,
                             on_command=lambda entry: self._emit("adb:command", entry))

    def _mirror_line(self, serial: str, line: str) -> None:
        self._session(serial).tagged("scrcpy").note(line)

    def _clean_screenshots(self) -> None:
        """Zrzuty bez zlecenia z poprzednich uruchomień: nie należą do protokołu (prywatność)."""
        try:
            with self._journal() as journal:
                delete_shots(journal, journal.orphan_screenshots())
        except Exception as exc:  # noqa: BLE001 — sprzątanie nie może zablokować startu okna
            log_exception(exc)

    def _purge_old_data(self) -> None:
        """Retencja przy starcie okna: zlecenia starsze niż okres z ustawień i stare logi."""
        try:
            now = self._now()
            if self._settings.retention_days:
                with self._journal() as journal:
                    retention.purge(journal, now, self._settings.retention_days, log_exception)
            retention.prune_logs(logs_dir(), now)
        except Exception as exc:  # noqa: BLE001 — sprzątanie nie może zablokować startu okna
            log_exception(exc)
        self._purge_transfers()

    def _purge_transfers(self) -> None:
        """Kopie danych po terminie (7 dni od utworzenia, chyba że przedłużone)."""
        try:
            store.purge_expired(self._now(), self._transfer_busy, self._copy_busy)
        except Exception as exc:  # noqa: BLE001 — sprzątanie nie może zablokować okna
            log_exception(exc)

    def _purge_loop(self, every: float) -> None:
        while not self._purge_stop.wait(every):
            self._purge_transfers()

    def _transfer_busy(self, serial: str) -> bool:
        """Czy trwa kopia tego telefonu. Zadanie kopii, które jeszcze nie zapisało telefonu,
        blokuje każdą kopię (ostrożnie: nie usuwamy tego, co może się właśnie wznawiać)."""
        job = self._jobs.current()
        if job is None or job.kind != "backup":
            return False
        busy = self._backup_serial
        return busy is None or busy == serial

    def _copy_busy(self, copy_id: str) -> bool:
        """Czy kopię czyta właśnie plan albo wgrywanie na nowy telefon (nie wolno jej usunąć, choćby
        była po terminie). Zadanie, które jeszcze nie zapisało kopii, blokuje każdą (jak wyżej)."""
        job = self._jobs.current()
        if job is None or job.kind not in RESTORE_KINDS:
            return False
        busy = self._restore_copy_id
        return busy is None or busy == copy_id

    def _restoring(self) -> str | None:
        """Id kopii, którą właśnie wgrywa zadanie `restore` (None — żadnej)."""
        job = self._jobs.current()
        return self._restore_copy_id if job is not None and job.kind == "restore" else None

    def _copy_view(self, meta: store.CopyMeta, now: datetime | None = None,
                   restoring: str | None = None) -> dict[str, Any]:
        """`now`/`restoring` podaje lista kopii (jeden odczyt na całą listę); domyślnie bieżące."""
        view = copy_view(meta, now or self._now(), restoring if now else self._restoring())
        # Wgrywania sprzed zapisu IMEI w stanie: IMEI z podłączonego telefonu, gdy już go odczytaliśmy.
        for r in view["restores"]:
            if r["imei"] is None and r["serial"] in self._identities:
                r["imei"] = self._identities[r["serial"]][1]
        return view

    def _bind_order(self, journal: Journal, serial: str, order_id: int) -> None:
        with self._shots_lock:
            pending = self._pending.pop(serial, [])
            journal.attach_screenshots(pending, order_id)
            self._open_order[serial] = order_id

    def _shot_view(self, shot: Screenshot) -> dict[str, Any]:
        png, jpg = screenshot_files(shot.id)
        return {"id": shot.id, "taken_at": shot.taken_at.isoformat(timespec="seconds"),
                "caption": screenshot_caption(shot.context, self._lang),
                "black": bool(shot.context.get("black")), "in_report": shot.in_report,
                "image": data_uri(jpg) or data_uri(png)}

    def _abandon_apk(self, notify: bool = True) -> None:
        with self._apk_commit:
            job = self._jobs.current()
            if job is not None and job.kind in ("apk", "deep") and self._jobs.abandon(job.id) and notify:
                # Bez `job_id`: UI zna już następne zadanie (cofnięcie, wznowienie) i odrzuciłoby
                # zdarzenie starego. Porzucone zadanie samo nic nie wyśle, gdy czekało na pytanie.
                # Nowy skan (notify=False) i tak zastępuje cały stan analizy.
                self._emit("apk:stopped", {})

    def _order_in_progress(self) -> Job | None:
        job = self._jobs.current()
        return job if job is not None and job.kind in ORDER_KINDS else None

    def _require_scan(self) -> None:
        if self._report is None or self._adb is None:
            raise AppError("no_scan")

    def _interrupted(self, device: DeviceInfo) -> list[str]:
        """Przerwane zlecenia tego telefonu — bez zleceń innego egzemplarza o tym samym numerze."""
        with self._journal() as journal:
            return [o.number for o in journal.interrupted_orders(device.serial)
                    if same_device(o.device_identity, device) is not False]

    def _note_version(self) -> str | None:
        """Wersja, do której program właśnie się zaktualizował — komunikat raz (spec §6.5)."""
        last = self._settings.last_run_version
        if last == __version__:
            return None
        try:
            self._settings = save_settings({"last_run_version": __version__})
        except SettingsTooNew:
            return None  # ustawień z nowszej wersji nie nadpisujemy
        if not last:
            return None  # pierwsze uruchomienie to nie aktualizacja
        try:
            newer = update.parse_version(last) < update.parse_version(__version__)
        except update.ManifestError:
            return None
        return __version__ if newer else None  # ręczne cofnięcie wersji to nie aktualizacja

    def _update_view(self) -> dict[str, Any]:
        return update_view(self._updates.state(), self._lang,
                           dismissed=self._settings.dismissed_update,
                           updated_to=self._updated_to, installable=self._frozen)

    def _require_current(self) -> None:
        """Wycofana wersja nie nakłada nowych zmian na telefon (spec aktualizacji §5)."""
        st = self._updates.state()
        if st.retired and st.manifest is not None:
            raise AppError("retired", st.manifest.reason_for(self._lang) or "",
                           min_supported=st.manifest.min_supported)

    def _start_telemetry(self) -> None:
        """Tylko z `run_gui`: wątek wysyłki i zdarzenie „start” (raz na dobę)."""
        telemetry.start(on_deleted=lambda: self._emit("telemetry:deleted", {}))
        telemetry.note_start(self._settings.mode, self._utc())

    def _stop_telemetry(self) -> None:
        telemetry.stop()

    def _start_updates(self) -> None:
        """Tylko z `run_gui`: sprzątanie starych instalatorów i wątek sprawdzania."""
        installer.cleanup()
        self._updates.start()

    def _device_list(self) -> dict[str, Any]:
        try:
            entries = list_devices(self._host)
        except AdbError as exc:
            return {"devices": [], "error": error_payload(exc)["key"]}
        crash.note_serials(e.serial for e in entries)
        ready = {e.serial for e in entries if e.state == "device"}
        self._explorer_presence(ready)
        for serial in set(self._identities) - ready:
            self._identities.pop(serial, None)  # odłączony: przy następnym podłączeniu czytamy od nowa
        with self._cleanup_lock:
            self._cleaned &= ready  # odłączony: przy następnym podłączeniu sprawdzamy od nowa
            self._check_failed &= ready
            self._cleanup_tries = {k: v for k, v in self._cleanup_tries.items() if k in ready}
            unchecked = sorted(ready - self._cleaned)
        for serial in unchecked:
            self._cleanup_on_connect(serial)
        devices = []
        for e in entries:
            name, imei, image, android = (self._identity(e.serial) if e.serial in ready
                                          else (None, None, None, None))
            devices.append({"serial": e.serial, "state": e.state, "model": e.model,
                            "name": name, "imei": imei, "image": image, "android": android})
        return {"devices": devices, "error": None}

    def _identity(self, serial: str) -> tuple[str | None, str | None, str | None, str | None]:
        """Nazwa handlowa, IMEI i obrazek telefonu już na ekranie podłączenia — raz na podłączenie, nie co
        odpytanie (zdarzenie `devices` idzie tylko przy zmianie, więc obrazek leci raz)."""
        if serial not in self._identities:
            try:
                device = read_device_info(self._session(serial))
            except AdbError:
                return None, None, None, None  # np. telefon jeszcze się nie odblokował: spróbujemy przy następnym
            self._remember(device, self._provider.match(device))
        return self._identities[serial]

    def _remember(self, device: DeviceInfo, match: PhoneMatch | None) -> None:
        card = device_card(device, match)
        self._identities[device.serial] = (card["name"], device.imei, card["image"] or None,
                                           device.android_release or None)

    def _cleanup_on_connect(self, serial: str) -> None:
        """Telefon pojawił się na liście: zmiany telefonu zostawione przez przerwane wgrywanie (rola SMS,
        appop, aplikacja pomocnicza) odwracamy najpierw, przed skanem i czymkolwiek innym (spec Etapu 3
        §4) — zadanie `phone_cleanup`; do jego końca każde inne zadanie dostaje `busy`. Gdy trwa inne
        zadanie, sprawdzamy przy następnym odczycie listy albo przy pierwszym wejściu zadania na tym
        telefonie (`_require_cleaned`). Błąd tu nie psuje listy telefonów (log raz na podłączenie)."""
        if self._jobs.current() is not None:
            return
        try:
            self._ensure_cleanup(serial, auto=True)
        except AppError:  # inne zadanie wystartowało w międzyczasie: spróbujemy przy następnym odczycie
            pass
        except Exception as exc:  # noqa: BLE001 — lista telefonów działa dalej
            with self._cleanup_lock:
                first = serial not in self._check_failed
                self._check_failed.add(serial)
            if first:  # odczyt co ~2 s: bez tego samego wpisu w logu przy każdym
                log_exception(exc)

    def _ensure_cleanup(self, serial: str, auto: bool = False) -> bool:
        """Sprawdza (raz na podłączenie) zmiany telefonu do odwrócenia i startuje `phone_cleanup`.
        True — sprzątanie wystartowało. Gdy trwa inne zadanie, a zmiany są: `AppError("busy", …)`
        z JobRunnera i telefon zostaje do sprawdzenia. Po nieudanym sprzątaniu: najwyżej
        `len(CLEANUP_BACKOFF)` prób na podłączenie, każda po odstępie z `CLEANUP_BACKOFF`. W odstępie
        odczyt listy telefonów (`auto`) nic nie robi, a wejście zadania dostaje `AppError("busy",
        "phone_cleanup")` bez nowej próby (szybkie kliknięcia nie zużywają prób; baner już jest). Po
        ostatniej nieudanej próbie nic nie startuje ani nie blokuje zadań na tym telefonie (czerwony baner
        ostrzega) aż do ponownego podłączenia."""
        with self._cleanup_lock:
            if serial in self._cleaned:
                return False
            failed, next_at = self._cleanup_tries.get(serial, (0, 0.0))
            if failed >= len(CLEANUP_BACKOFF):
                return False
            if self._clock() < next_at:
                if auto:
                    return False
                raise AppError("busy", "phone_cleanup")
            copies = []
            for meta in store.list_copies():
                with contextlib.suppress(ValueError, OSError):
                    copies.append(store.copy_dir(meta.id))
            paths = pending_cleanup(copies, serial)
            self._check_failed.discard(serial)
            self._cleaned.add(serial)
            if not paths:
                return False
            try:
                self._jobs.start("phone_cleanup", lambda job: self._phone_cleanup(job, serial, paths))
            except AppError:
                self._cleaned.discard(serial)
                raise
            return True

    def _require_cleaned(self, serial: str) -> None:
        """Wejście zadania na telefonie `serial`: najpierw sprzątanie zmian telefonu (spec Etapu 3 §4),
        także gdy w chwili podłączenia trwało inne zadanie albo obserwator telefonów był wyłączony."""
        if self._ensure_cleanup(serial.strip()):
            raise AppError("busy", "phone_cleanup")

    def _phone_cleanup(self, job: Job, serial: str, paths: list[Path]) -> None:
        ok = False
        adb = self._session(serial)
        self._emit("transfer:cleanup_started", {"serial": serial})
        try:
            with _transfer_errors("phone_cleanup"), device_lock(journal_path(), serial):
                ok = True
                for path in paths:
                    if job.should_stop():
                        ok = False
                        break
                    state = open_changes(path)  # stan wgrywania albo sam zapis telefonu (kopia usunięta)
                    try:
                        res = cleanup(telephony_adb(adb, state), state, self._tap_handler(state), job.should_stop)
                    finally:
                        state.close()
                    ok = ok and res.ok
        except BaseException:
            ok = False
            raise
        finally:
            self._end_tap()
            with self._cleanup_lock:
                if ok:
                    self._cleanup_tries.pop(serial, None)
                elif not job.should_stop():
                    # nieudane (nie zatrzymane przez serwisanta): ponowienie w tle po odstępie przy odczycie
                    # listy albo przy wejściu zadania, najwyżej `len(CLEANUP_BACKOFF)` prób na podłączenie;
                    # zatrzymane nie pyta znów w tym podłączeniu
                    failed = self._cleanup_tries.get(serial, (0, 0.0))[0] + 1
                    wait = CLEANUP_BACKOFF[failed] if failed < len(CLEANUP_BACKOFF) else 0.0
                    self._cleanup_tries[serial] = (failed, self._clock() + wait)
                    self._cleaned.discard(serial)
            self._emit("transfer:cleanup_done", {"ok": ok, "serial": serial})

    def _tap_handler(self, state: Changes) -> Callable[[str | None], None]:
        """`on_tap` silnika: zdarzenie `transfer:tap` z prośbą i poprzednią domyślną aplikacją SMS
        (`role_prev[0]` ze stanu wgrywania; UI pokazuje jej nazwę)."""

        def on_tap(request: str | None) -> None:
            if request == "sms_role_grant":
                self._skip_tap.clear()
            self._tap_request = request
            prev = device_changes(state).role_prev
            self._emit("transfer:tap", {"request": request, "package": prev[0] if prev else None})

        return on_tap

    def _end_tap(self) -> None:
        self._tap_request = None
        self._skip_tap.clear()

    # --- ustawienia i telefony --------------------------------------------------------------

    @_api
    def get_settings(self) -> dict[str, Any]:
        return {**asdict(self._settings), "lang": self._lang,
                "welcome_current": welcome.WELCOME_VERSION,
                "telemetry_delete_pending": telemetry.delete_pending(),
                "donate_reminders": not self._settings.donate_off}

    @_api
    def accept_welcome(self, telemetry_on: bool, packages: bool) -> dict[str, Any]:
        if not isinstance(telemetry_on, bool) or not isinstance(packages, bool):
            raise AppError("bad_request", "consent")
        # Najpierw zgody: SettingsTooNew przerywa przed zapisem akceptacji ostrzeżenia.
        telemetry.set_consent(telemetry_on, packages, self._utc())
        self._settings = welcome.accept_risk(self._utc())
        self._note_start()
        return self.get_settings()

    @_api
    def set_telemetry(self, telemetry_on: bool, packages: bool) -> dict[str, Any]:
        if not isinstance(telemetry_on, bool) or not isinstance(packages, bool):
            raise AppError("bad_request", "consent")
        self._settings = telemetry.set_consent(telemetry_on, packages, self._utc())
        self._note_start()
        return self.get_settings()

    def _note_start(self) -> None:
        """„start” także w dniu udzielenia zgody (przy starcie okna zgody jeszcze nie było)."""
        telemetry.note_start(self._settings.mode, self._utc())
        self._settings = load_settings()  # telemetry_start_day

    @_api
    def telemetry_sample(self) -> dict[str, Any]:
        return sample()

    @_api
    def open_privacy(self) -> dict[str, Any]:
        self._open_url(f"{client.base_url()}/{'pl/' if self._lang == 'pl' else ''}privacy")
        return {"ok": True}

    @_api
    def open_donate(self) -> dict[str, Any]:
        self._open_url(f"{client.base_url()}/{'pl/' if self._lang == 'pl' else ''}donate")
        return {"ok": True}

    @_api
    def set_donate_reminders(self, on: bool) -> dict[str, Any]:
        if not isinstance(on, bool):
            raise AppError("bad_request", "donate")
        self._settings = donate.set_reminders(on)
        return self.get_settings()

    @_api
    def save_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        limit = changes.get("apk_cache_limit_gb")
        if isinstance(limit, int) and not isinstance(limit, bool):
            try:
                too_big = limit * GB > disk_total(default_cache_dir())
            except OSError:  # spec §6: bez znanej pojemności dysku pomijamy górną granicę
                too_big = False
            if too_big:
                raise AppError("bad_request", "apk_cache_limit_gb")
        pdf_dir = changes.get("report_pdf_dir")
        if isinstance(pdf_dir, str) and pdf_dir.strip() and not archive_dir_ok(pdf_dir.strip()):
            raise AppError("bad_request", "report_pdf_dir")  # UI pokazuje to przy polu
        self._settings = save_settings(dict(changes))
        if "lang" in changes:
            self._lang = effective_lang(self._settings)
        if "adb_path" in changes:
            self._host = self._host_factory(self._settings.adb_path)
        if changes.get("check_updates") is True:
            self._updates.poke()
        return self.get_settings()

    @_api
    def list_devices(self) -> dict[str, Any]:
        return self._device_list()

    @_api
    def watch_devices(self, on: bool) -> dict[str, Any]:
        if on:
            self._watcher.start()
        else:
            self._watcher.stop()
        return {"ok": True}

    # --- skan i analiza APK ------------------------------------------------------------------

    @_api
    def start_scan(self, serial: str, client: str | None = None) -> dict[str, Any]:
        if not isinstance(serial, str) or not serial.strip():
            raise AppError("bad_request", "serial")
        self._require_explorer_free(serial)
        self._require_cleaned(serial)
        self._abandon_apk(notify=False)
        with self._shots_lock:
            self._open_order.pop(serial.strip(), None)
        adb = self._session(serial.strip())
        name = (client or "").strip() or None
        crash.note_names([name])

        def run(job: Job) -> None:
            self._emit("scan:stage", {"stage": "identify"})
            device = read_device_info(adb)
            crash.note_device(device.serial, device.manufacturer, device.model, device.android_release)
            match = self._provider.match(device)
            self._remember(device, match)
            self._adb, self._serial, self._client = adb, device.serial, name
            self._report, self._match = None, match
            session = secrets.token_hex(4)
            self._scan_session = session
            started = time.monotonic()
            self._emit("scan:device", {"device": device_card(device, match)})
            if os.environ.get(crash.CRASH_TEST) == "error":  # próba ręczna (spec raportów §10.2)
                raise RuntimeError(crash.CRASH_TEST)
            incidents = load_incident(incident_path(device.serial), self._now())
            # Nazwy z telefonu równolegle ze skanem — w trybie ręcznym bez APK nie ma innych.
            labels = self._fetch_labels(device.serial) if self._apk_factory is not None else None
            try:
                report = run_scan(adb, device=device, incidents=incidents,
                                  on_stage=lambda stage: self._emit("scan:stage", {"stage": stage}))
                job.check()
                self._report = scanned = report
                self._emit("scan:done", {"scan": scan_view(report, self._lang),
                                         "interrupted": self._interrupted(device),
                                         "client": name})
                telemetry.record("scan", lambda p: scan_event(scanned, session,
                                                              int(time.monotonic() - started), p))
                if labels is None:
                    return
                job.kind = "apk"  # od teraz nowy skan porzuca to zadanie (`_abandon_apk`)
                self._estimate, self._eta = None, None
                # Wyniki są już na ekranie; nazwy (i DM-LABEL-02) wchodzą przed wyborem trybu,
                # a raport z nimi publikuje dopiero `_run_apk` (apk:manual / apk:done).
                report = apply_phone_labels(report, labels.wait(job.check))
                job.check()
            finally:
                if labels is not None:
                    labels.cancel()
            self._run_apk(job, adb, report, choose=True)

        self._estimate, self._eta = None, None  # nowy telefon: stary szacunek nie obowiązuje
        return {"job_id": self._jobs.start("scan", run)}

    def _fetch_labels(self, serial: str) -> LabelFetch:
        adb = resolve_adb(self._settings.adb_path).path
        log = self._session(serial).tagged("scrcpy")

        def fetch(stop: threading.Event) -> dict[str, PhoneLabel]:
            self._wait_mirror_start(serial, stop)
            return self._app_labels(serial, adb, stop, log.note)

        if self._labels is not None:
            self._labels.cancel()  # poprzedni skan: jego scrcpy już niepotrzebny
        self._labels = LabelFetch(fetch, log_exception)
        return self._labels

    def _wait_mirror_start(self, serial: str, stop: threading.Event) -> None:
        deadline = time.monotonic() + SCRCPY_TURN_WAIT_S
        while time.monotonic() < deadline and not stop.is_set():
            status = self._mirror.status()
            if status.get("serial") != serial or status.get("state") != "starting":
                return
            stop.wait(0.2)

    def _cache_limit(self) -> int:
        return self._settings.apk_cache_limit_gb * GB

    def _run_apk(self, job: Job, adb: AdbTransport, report: ScanReport,
                 deep: frozenset[str] = frozenset(), only: frozenset[str] = frozenset(),
                 choose: bool = False) -> None:
        started = time.monotonic()
        speeds = load_speeds()
        whole = not deep and not only  # pełny zakres: szacunek przyda się później
        provider: ApkProvider | None = None

        def workers() -> int:
            return getattr(provider, "workers", 1)

        def ask(payload: dict[str, Any]) -> str | None:
            # Czas namysłu serwisanta nad pytaniem to nie czas analizy (telemetria `seconds`).
            nonlocal started
            asked = time.monotonic()
            answer = job.ask("apk:question", payload)
            started += time.monotonic() - asked
            return answer

        def decide(est: Estimate, use: CacheUsage) -> str:
            # Zatrzymanie zadania w trakcie pytania (None) = pominięcie; `job.check` niżej kończy.
            return ask({"kind": "no_space", **estimate_view(est, use)}) or "skip"

        def on_estimate(est: Estimate, use: CacheUsage) -> None:
            eta = estimate_eta(est, speeds, workers())
            if whole:
                self._estimate, self._eta = est, eta
            # `scope`: UI trzyma czas „Przeanalizuj wszystko” tylko z szacunku całego telefonu.
            self._emit("apk:estimate", {**estimate_view(est, use), **eta_view(eta),
                                        "scope": "all" if whole else "part", "job_id": job.id})

        def pick(est: Estimate | None, use: CacheUsage | None, apps: int) -> str:
            eta = estimate_eta(est, speeds, workers()) if est is not None else None
            self._estimate, self._eta = est, eta
            default = self._settings.apk_mode_default
            if default != "ask":
                return default
            sizes = estimate_view(est, use) if est is not None and use is not None else {}
            # Zatrzymanie w trakcie pytania (None) = tryb ręczny: nic nie pobieramy (spec §2.1 p. 5).
            answer = ask({"kind": "mode", "apps": apps, **sizes, **eta_view(eta)})
            return answer if answer in ("full", "manual") else "manual"

        policy = CachePolicy(self._cache_limit(), on_estimate=on_estimate, decide=decide,
                             choose=pick if choose else None)
        provider = self._apk_factory(adb, policy=policy, deep=deep)

        def progress(done: int, total: int, package: str) -> None:
            job.check()
            eta = live_eta(speeds, getattr(provider, "stats", None),
                           getattr(provider, "estimate", None), total - done, workers())
            self._emit("apk:progress", {"done": done, "total": total, "package": package,
                                        "eta_s": eta, "job_id": job.id})

        try:
            updated = analyze_apks(report, provider, progress, only=deep or only or None)
            with self._apk_commit:  # sprawdzenie i zapis atomowo względem `_abandon_apk`
                job.check()
                self._report = updated = self._keep_checks(updated)
                self._emit("apk:done", {"scan": scan_view(updated, self._lang), "job_id": job.id})
        except ManualMode:
            self._publish_manual(job, report, started, record=whole)
            return
        except Stopped:
            if not deep:
                self._learn(speeds, provider)
            # `finally` czyści `_to_manual` dopiero po tym odczycie — nie przenoś go wyżej.
            if self._to_manual == job.id:
                self._publish_manual(job, report, started, record=whole)
            else:
                self._emit("apk:stopped", {"job_id": job.id})
            return
        finally:
            if self._to_manual == job.id:
                self._to_manual = None
        if not deep:
            self._learn(speeds, provider)
        if whole:  # głęboka analiza i analiza zaznaczonych to nie nowa ocena telefonu
            session = self._scan_session or ""
            eta = self._eta
            telemetry.record("scan", lambda p: scan_event(updated, session,
                                                          int(time.monotonic() - started), p,
                                                          apk_stage=True, eta=eta))

    def _keep_checks(self, report: ScanReport) -> ScanReport:
        """Raport z analizy APK powstał z kopii sprzed ewentualnego `recheck_site_notifications`:
        kontrole zostają te nowsze. Wołać pod `_apk_commit`."""
        current = self._report
        if current is None or current.device_checks is report.device_checks:
            return report
        return replace(report, device_checks=current.device_checks)

    def _learn(self, speeds: Speeds, provider: ApkProvider | None) -> None:
        stats = getattr(provider, "stats", None)
        if stats is None:
            return
        new = learn(speeds, stats)
        if new != speeds:
            try:
                save_speeds(new)
            except OSError:
                pass  # brak zapisu = następny szacunek z poprzedniej historii

    def _publish_manual(self, job: Job, report: ScanReport, started: float, record: bool) -> None:
        """Tryb ręczny po wyborze albo po „Przerwij i szukaj ręcznie” (spec §2.2).

        `record`: tylko przebieg całego telefonu jest nową oceną w telemetrii — przerwana
        analiza zaznaczonych zostawia ocenę z wyboru trybu.
        """
        mode = "partial" if report.analyzed_on_demand else "manual"
        with self._apk_commit:
            # `job.check` nie wchodzi w grę (zadanie bywa zatrzymane celowo); porzucone przez
            # nowy skan albo wykonanie nie jest już bieżące — wtedy nic nie publikujemy.
            if self._jobs.current() is not job:
                return
            published = self._report = self._keep_checks(replace(report, apk_mode=mode))
            self._emit("apk:manual", {"scan": scan_view(published, self._lang), "job_id": job.id})
        if not record:
            return
        session, eta = self._scan_session or "", self._eta
        telemetry.record("scan", lambda p: scan_event(published, session,
                                                      int(time.monotonic() - started), p,
                                                      apk_stage=True, eta=eta))

    @_api
    def deep_analyze(self, package: str) -> dict[str, Any]:
        """Głęboka analiza jednej aplikacji (ścieżki w kodzie) — tylko na żądanie, ocena §6, §8."""
        self._require_scan()
        self._require_explorer_free(self._serial or "")
        if self._apk_factory is None:
            raise AppError("bad_request", "apk")
        report = self._report
        if not isinstance(package, str) or package not in {r.facts.package for r in report.results}:
            raise AppError("bad_request", "package")
        adb = self._adb

        def run(job: Job) -> None:
            self._run_apk(job, adb, report, deep=frozenset({package}))

        return {"job_id": self._jobs.start("deep", run)}

    @_api
    def analyze_selected(self, packages: list[str]) -> dict[str, Any]:
        """Analiza tylko wskazanych aplikacji (tryb ręczny, spec §2.2)."""
        self._require_scan()
        self._require_explorer_free(self._serial or "")
        if self._apk_factory is None:
            raise AppError("bad_request", "apk")
        report = self._report
        known = {r.facts.package for r in report.results}
        if (not isinstance(packages, list) or not packages
                or not all(isinstance(p, str) and p in known for p in packages)):
            raise AppError("bad_request", "packages")
        adb, chosen = self._adb, frozenset(packages)

        def run(job: Job) -> None:
            self._run_apk(job, adb, report, only=chosen)

        return {"job_id": self._jobs.start("apk", run)}

    @_api
    def analyze_all(self) -> dict[str, Any]:
        """Pełna analiza z trybu ręcznego — bez ponownego pytania o tryb."""
        self._require_scan()
        self._require_explorer_free(self._serial or "")
        if self._apk_factory is None:
            raise AppError("bad_request", "apk")
        adb, report = self._adb, self._report

        def run(job: Job) -> None:
            self._run_apk(job, adb, report)

        return {"job_id": self._jobs.start("apk", run)}

    @_api
    def stop_apk_to_manual(self) -> dict[str, Any]:
        job = self._jobs.current()
        if job is None or job.kind != "apk":
            raise AppError("bad_request", "job")
        self._to_manual = job.id
        self._jobs.stop(job.id)
        return {"ok": True}

    @_api
    def selection_eta(self, packages: list[str]) -> dict[str, Any]:
        """Czas analizy zaznaczonych — z ostatniego pełnego szacunku, bez telefonu."""
        est = self._estimate
        if est is None or not isinstance(packages, list) or not all(isinstance(p, str) for p in packages):
            return eta_view(None)
        return eta_view(estimate_eta(est, load_speeds(), DEFAULT_WORKERS, packages))

    @_api
    def who_is_showing(self) -> dict[str, Any]:
        if self._adb is None:
            raise AppError("no_device")
        job = self._order_in_progress()
        if job is not None:
            raise AppError("busy", job.kind)
        fg = read_foreground(self._adb.tagged("who"))
        names = self._names()

        def entry(package: str) -> dict[str, str]:
            return {"package": package, "name": names.get(package, package)}

        return {"resumed": entry(fg.resumed) if fg.resumed else None,
                "overlays": None if fg.overlays is None else [entry(p) for p in fg.overlays],
                "errors": fg.errors}

    # --- nagranie incydentu (ocena §7.4) -----------------------------------------------------------

    @_api
    def start_incident(self, seconds: float = 120.0) -> dict[str, Any]:
        """Nagrywa, kto rysuje ekran; `mark_incident` = „reklama jest teraz na ekranie”.

        Osobny wątek, nie zadanie: nagrywanie ma działać także w trakcie analizy APK po skanie.
        """
        if self._adb is None or self._serial is None:
            raise AppError("no_device")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float))                 or not 10 <= seconds <= INCIDENT_MAX_S:
            raise AppError("bad_request", "seconds")
        with self._incident_lock:
            if self._incident_active:
                raise AppError("busy", "incident")
            self._incident_active = True
            self._incident_mark.clear()
        adb, serial, names = self._adb.tagged("who"), self._serial, self._names()

        def poll_mark() -> bool:
            hit = self._incident_mark.is_set()
            self._incident_mark.clear()
            return hit

        def run() -> None:
            try:
                timeline = self._incident_record(adb, float(seconds), INCIDENT_INTERVAL_S,
                                                 poll_mark=poll_mark)
                save_incident(incident_path(serial), timeline, self._now())  # bez znaczników: nie zapisuje
                hits = [{"mark": a.mark, "package": a.package, "name": names.get(a.package, a.package),
                         "kind": a.kind, "over": a.over,
                         "over_name": names.get(a.over, a.over) if a.over else None}
                        for a in attribute(timeline)]
                self._emit("incident:done", {"marks": len(timeline.marks), "hits": hits})
            except Exception as exc:  # noqa: BLE001 — błąd nagrania trafia do UI
                self._emit("incident:done", {"marks": 0, "hits": [], "error": report_error(exc, {"job": "incident"})})
            finally:
                with self._incident_lock:
                    self._incident_active = False

        self._emit("incident:state", {"recording": True, "seconds": seconds})
        if self._sync:
            run()
        else:
            threading.Thread(target=run, daemon=True, name="admenot-incident").start()
        return {"ok": True}

    @_api
    def mark_incident(self) -> dict[str, Any]:
        with self._incident_lock:
            if not self._incident_active:
                raise AppError("bad_request", "not recording")
            self._incident_mark.set()
        return {"ok": True}

    @_api
    def recheck_site_notifications(self, when_debugging: bool = False) -> dict[str, Any]:
        """Ponowny odczyt samej kontroli powiadomień witryn (po zmianie na telefonie), bez skanu.

        `when_debugging`: odpytywanie w tle — pełny odczyt tylko wtedy, gdy na telefonie pojawiło
        się zdalne debugowanie przeglądarki z podpowiedzią; inaczej `check` = None."""
        self._require_scan()
        job = self._order_in_progress()
        if job is not None:
            raise AppError("busy", job.kind)
        adb, report, shown = self._adb, self._report, self._plans_shown
        if when_debugging:
            old = next((c for c in report.device_checks if c.id == SITE_NOTIFICATIONS), None)
            if old is None or not debugging_appeared(adb.tagged("recheck"), old):
                return {"check": None}
        labels = {r.facts.package: r.facts.label for r in report.results}
        check = read_site_notifications(adb.tagged("recheck"), labels)
        with self._apk_commit:  # nie rozjeżdżamy się z zapisem wyniku analizy APK
            current = self._report
            # nowy skan już ma własne kontrole; plan pokazany w trakcie odczytu zostaje przy starych
            if self._adb is adb and current is not None and self._plans_shown == shown:
                known = {c.id for c in current.device_checks}
                checks = [check if c.id == check.id else c for c in current.device_checks]
                self._report = replace(current, device_checks=checks if check.id in known
                                       else [*checks, check])
        return {"check": device_checks_view([check], self._lang, labels)[0]}

    @_api
    def rerender(self) -> dict[str, Any]:
        return {"scan": scan_view(self._report, self._lang) if self._report else None}

    # --- podgląd ekranu (Plan 6b §4.1) ----------------------------------------------------------

    @_api
    def mirror_status(self) -> dict[str, Any]:
        return self._mirror.status()

    @_api
    def mirror_start(self, serial: str, name: str | None = None) -> dict[str, Any]:
        if not isinstance(serial, str) or not serial.strip():
            raise AppError("bad_request", "serial")
        if name is not None and not isinstance(name, str):
            raise AppError("bad_request", "name")
        serial = serial.strip()
        title = f"AdMeNot — {(name or '').strip() or serial}"
        if self._labels is not None:
            self._labels.wait(timeout=SCRCPY_TURN_WAIT_S)  # SCRCPY_TURN_WAIT_S: jeden scrcpy naraz
        try:
            return self._mirror.start(serial, title)
        except MirrorUnavailable:
            raise AppError("mirror_missing") from None

    @_api
    def mirror_stop(self) -> dict[str, Any]:
        self._mirror.stop()
        return {"ok": True}

    # --- zrzuty ekranu (Plan 6b §4.2, §5) --------------------------------------------------------

    @_api
    def screenshot(self, serial: str) -> dict[str, Any]:
        if not isinstance(serial, str) or not serial.strip():
            raise AppError("bad_request", "serial")
        serial = serial.strip()
        # Zrzut działa też przed skanem (ekran Połącz) i w trakcie zlecenia: tylko czyta telefon.
        adb = self._adb if self._adb is not None and self._serial == serial else self._session(serial)
        names = self._names() if self._serial == serial else {}
        order_id = self._open_order.get(serial)
        with self._journal() as journal:
            shot = take_screenshot(adb.tagged("shot"), journal, serial, names, order_id)
            # `order_id` był czytany przed wolnym screencapem: zlecenie mogło się otworzyć w
            # międzyczasie (Napraw robi plan_order, a serwisant klika zrzut) — bez tej blokady i
            # ponownego odczytu zrzut zostałby osierocony albo trafił do złego, późniejszego
            # zlecenia (przegląd Task 8, runda 1).
            with self._shots_lock:
                open_id = self._open_order.get(serial)
                if shot.order_id is None and open_id is not None:
                    journal.attach_screenshots([shot.id], open_id)
                    shot = journal.screenshot(shot.id)
                elif shot.order_id is None:
                    self._pending.setdefault(serial, []).append(shot.id)
            if shot.order_id is not None:
                count = sum(1 for s in journal.screenshots(shot.order_id) if s.in_report)
            else:
                with self._shots_lock:
                    pending = list(self._pending.get(serial, ()))
                count = sum(1 for i in pending if journal.screenshot(i).in_report)
            count = min(count, MAX_REPORT_SCREENSHOTS)
        return {"shot": self._shot_view(shot), "count": count}

    @_api
    def close_order(self, serial: str) -> dict[str, Any]:
        """Serwisant zostawia zlecenie („Nowe skanowanie”): kolejne zrzuty czekają na następne."""
        if not isinstance(serial, str) or not serial.strip():
            raise AppError("bad_request", "serial")
        with self._shots_lock:
            self._open_order.pop(serial.strip(), None)
        return {"ok": True}

    @_api
    def screenshots(self, order: str) -> dict[str, Any]:
        if not isinstance(order, str) or not order.strip():
            raise AppError("bad_request", "order")
        number = order.strip()
        with self._journal() as journal:
            found = journal.order_by_number(number)
            if found is None:
                raise AppError("unknown_order", number)
            shots = journal.screenshots(found.id)
        return {"order": number, "limit": MAX_REPORT_SCREENSHOTS,
                "items": [self._shot_view(s) for s in shots]}

    @_api
    def set_screenshot_in_report(self, shot_id: int, on: bool) -> dict[str, Any]:
        if isinstance(shot_id, bool) or not isinstance(shot_id, int) or not isinstance(on, bool):
            raise AppError("bad_request", "shot")
        with self._journal() as journal:
            try:
                shot = journal.set_screenshot_in_report(shot_id, on)
            except KeyError:
                raise AppError("unknown_screenshot", str(shot_id)) from None
            except ScreenshotLimit:
                raise AppError("shot_limit", str(MAX_REPORT_SCREENSHOTS)) from None
        return self._shot_view(shot)

    # --- plan i wykonanie --------------------------------------------------------------------

    def _names(self) -> dict[str, str]:
        if self._report is None:
            return {}
        return self._with_browsers(
            {r.facts.package: app_name(r.facts, r.facts.package) for r in self._report.results},
            self._report)

    @staticmethod
    def _with_browsers(names: dict[str, str], report: ScanReport | None) -> dict[str, str]:
        """Przeglądarki, które zlecenie zmienia tylko w ustawieniach witryn, mogą nie być w `names` albo
        mieć tam sam pakiet (etykieta nieodczytana, przeglądarki zwykle nie analizujemy)."""
        for package, name in browser_names(report.device_checks if report else []).items():
            if names.get(package, package) == package:
                names[package] = browser_name(package, {package: name})
        return names

    def _site_view(self, journal: Journal, action_id: int, names: dict[str, str]) -> dict[str, Any]:
        """Przeglądarka i witryna kroku `channel` z dziennika (`site` None = wspólny kanał przeglądarki)."""
        step = journal.action(action_id).step
        return {"browser": browser_name(step["package"], names),
                "site": fix_step_texts(step, self._lang, names)["site"]}

    def _options(self, job: Job, manufacturer: str, names: dict[str, str],
                 journal: Journal | None = None, order: str | None = None) -> ExecOptions:
        def waiting_on(event: dict[str, Any]) -> dict[str, Any]:
            package = event["package"]
            wait: dict[str, Any] = {"package": package, "name": names.get(package, package),
                                    "kind": event["step"], "timeout": event["timeout"],
                                    "action_id": event["action_id"]}
            if event["step"] == "channel" and journal is not None:  # witryna: z kroku w dzienniku
                site = self._site_view(journal, event["action_id"], names)
                wait["browser"] = site["browser"]
                if site["site"]:
                    wait["site"] = site["site"]
            return wait

        def on_event(event: dict[str, Any]) -> None:
            kind = event["type"]
            if kind == "step":
                self._emit("exec:step", step_view(event, self._lang, manufacturer, names))
            elif kind == "undo":
                self._emit("undo:step", step_view(event, self._lang, manufacturer, names))
            elif kind == "undo_sites" and journal is not None:  # kolejka witryn, zanim otworzy się pierwsza
                self._emit("undo:sites", {"order": order, "sites": [
                    {"action_id": s["action_id"], "package": s["package"],
                     **self._site_view(journal, s["action_id"], names)} for s in event["sites"]]})
            elif kind == "user_wait":
                self._skip.clear()  # liczy się tylko „Pomiń” kliknięte przy tym ekranie
                self._emit("exec:user_wait", waiting_on(event))
            elif kind == "user_done":
                self._emit("exec:user_done", {"package": event["package"], "status": event["status"]})
            elif kind == "verify":
                self._emit("exec:verify", {})

        def on_admin_timeout(package: str) -> str:
            answer = job.ask("exec:question", {"kind": "user_timeout", "package": package,
                                               "name": names.get(package, package)})
            return "retry" if answer == "retry" else "skip"

        self._reopen.clear()  # prośba sprzed tego zlecenia nie dotyczy jego kroków

        def reopen() -> bool:
            if self._reopen.is_set():
                self._reopen.clear()
                return True
            return False

        self._skip.clear()  # tak samo „Pomiń”: dotyczy tylko ekranów tego cofania

        def skip() -> bool:
            if self._skip.is_set():
                self._skip.clear()
                return True
            return False

        return ExecOptions(apk_cache_dir=default_cache_dir(), admin_timeout=self._admin_timeout,
                           poll_interval=self._poll_interval, on_event=on_event,
                           on_admin_timeout=on_admin_timeout, should_stop=job.should_stop,
                           reopen=reopen, skip=skip)

    def _run_order(self, job: Job, adb: AdbTransport, journal: Journal, order: Order,
                   manufacturer: str, names: dict[str, str],
                   runner: Runner) -> tuple[OrderResult | None, str | None]:
        """(wynik, przerwanie): przerwanie = None | "stopped" | "disconnected" (telemetria)."""
        try:
            result = execute_order(adb, journal, order,
                                   self._options(job, manufacturer, names, journal), runner)
        except OrderInterrupted as exc:
            self._emit("exec:disconnected", {"order": exc.order.number})
            return None, "disconnected"
        if result.stopped:
            self._emit("exec:stopped", {"order": order.number})
        clear_cache_after_repair(result, self._settings, default_cache_dir())
        reminder = False
        if donate.succeeded(result):  # także zlecenie dokończone przez resume
            reminder = donate.note_success(self._now())
            self._settings = load_settings()
        # Zgoda Firefoxa zmieniona przez zdalne debugowanie: UI przypomina o jego wyłączeniu.
        debugging = any(a.step["kind"] == "site_permission" and a.status == "done"
                        for a in journal.actions(order.id))
        self._emit("exec:done", {**result_view(result, names, self._lang, manufacturer),
                                 "donate_reminder": reminder, "firefox_debugging": debugging})
        return result, "stopped" if result.stopped else None

    @_api
    def preview_plan(self, requests: dict[str, str], unlocked: list[str] | None = None,
                     fixes: list[str] | None = None) -> dict[str, Any]:
        wanted = _fixes(fixes)
        self._require_scan()
        self._plans_shown += 1
        plan = plan_order(self._adb, self._report, dict(requests), unlocked or (), fixes=wanted)
        return plan_view(plan, self._lang)

    @_api
    def share_plan(self, requests: dict[str, str], unlocked: list[str] | None,
                   share_id: str, fixes: list[str] | None = None) -> dict[str, Any]:
        """Plan dla klienta (spec plan-qr §5.3): wynik przychodzi zdarzeniem `share:ready|failed`."""
        if not isinstance(share_id, str) or not _SHARE_ID.fullmatch(share_id):
            raise AppError("bad_request", "share_id")
        wanted = _fixes(fixes)
        self._require_scan()
        self._plans_shown += 1
        plan = plan_order(self._adb, self._report, dict(requests), unlocked or (), fixes=wanted)
        if not plan.plans:
            raise AppError("nothing_to_do")
        names = {p: app_name(f, p) for p, f in plan.facts.items()}
        at = self._now()
        common = {"lang": self._lang, "phone": device_card(plan.device, self._match)["name"],
                  "at": at, "names": names, "shop": load_service().name,
                  "partial": self._report.apk_mode != "full",
                  "fix_texts": fix_texts(plan, self._lang)}
        full = share.fit(share.build_payload(plan, **common))
        local = share.local_url(client.base_url(), share.build_payload(plan, icons=False, **common))
        code = full["code"]
        self._shown.pop(code, None)
        self._shown[code] = at
        while len(self._shown) > SHOWN_MAX:
            del self._shown[next(iter(self._shown))]
        cancel = threading.Event()
        with self._share_lock:
            if self._share_cancel is not None:
                self._share_cancel[1].set()
            self._share_cancel = (share_id, cancel)

        def emit(name: str, detail: dict[str, Any]) -> None:
            if not cancel.is_set():
                self._emit(name, {"share_id": share_id, "code": code, **detail})

        def run() -> None:
            deadline = time.monotonic() + self._share_retry_window_s
            first = True
            while not cancel.is_set():
                try:
                    blob, key = share.encrypt(full)
                    sid, expires = self._share_upload(blob)
                    emit("share:ready", {"url": share.server_url(client.base_url(), sid, key),
                                         "mode": "server", "expires": expires})
                    return
                except BackendError as exc:
                    if first:
                        first = False
                        # offline=False: serwer odpowiedział błędem (np. stara wersja), a nie brak sieci.
                        offline = exc.kind == "offline"
                        if local is not None:
                            emit("share:ready", {"url": local, "mode": "local", "expires": None,
                                                 "offline": offline})
                        else:
                            emit("share:failed", {"reason": "too_long", "offline": offline})
                except Exception as exc:  # noqa: BLE001 — błąd przygotowania trafia do UI i logu
                    report_error(exc, {"call": "share_plan"})
                    emit("share:failed", {"reason": "error"})
                    return
                if time.monotonic() >= deadline or cancel.wait(self._share_retry_s):
                    return

        if self._sync:
            run()
        else:
            threading.Thread(target=run, daemon=True, name="admenot-share").start()
        return {"share_id": share_id, "code": code}

    @_api
    def cancel_share(self, share_id: str) -> dict[str, Any]:
        """Przerywa tylko wskazane udostępnienie: spóźnione anulowanie starego kodu nie rusza nowego."""
        with self._share_lock:
            if self._share_cancel is not None and self._share_cancel[0] == share_id:
                self._share_cancel[1].set()
                self._share_cancel = None
        return {"ok": True}

    @_api
    def execute(self, requests: dict[str, str], unlocked: list[str] | None = None,
                consent: dict[str, Any] | None = None,
                fixes: list[str] | None = None) -> dict[str, Any]:
        self._require_current()
        wanted_fixes = _fixes(fixes)
        self._require_scan()
        if consent is not None and not (isinstance(consent, dict) and isinstance(consent.get("code"), str)):
            raise AppError("bad_request", "consent")
        if self._serial is not None:
            self._require_cleaned(self._serial)
        self._abandon_apk()
        adb, report, match, client = self._adb, self._report, self._match, self._client
        wanted, free = dict(requests), list(unlocked or ())

        def run(job: Job) -> None:
            plan = plan_order(adb, report, wanted, free, fixes=wanted_fixes)
            if not plan.plans:
                raise AppError("nothing_to_do")
            agreed = None
            if consent is not None:
                # Zgoda dotyczy dokładnie pokazanego planu — inny plan nie rusza (spec plan-qr §5.3).
                shown = self._shown.get(consent["code"])
                if shown is None or share.plan_code(plan) != consent["code"]:
                    raise AppError("plan_changed")
                agreed = {"code": consent["code"], "shown_at": shown.isoformat(timespec="seconds"),
                          "confirmed_at": self._now().isoformat(timespec="seconds")}
            names = self._with_browsers({p: app_name(f, p) for p, f in plan.facts.items()}, report)
            with self._journal() as journal:
                order = start(journal, plan, client, report, match, agreed)
                self._bind_order(journal, plan.device.serial, order.id)
                self._emit("exec:order", {"order": order.number,
                                          "plan": plan_view(plan, self._lang)})
                result, interrupted = self._run_order(job, adb, journal, order,
                                                      plan.ctx.manufacturer, names, run_order)
                actions = journal.actions(order.id)
            verdicts = {r.facts.package: r.verdict for r in report.results}
            session = self._scan_session or ""
            blind = (frozenset(p.package for p in plan.plans) - report.analyzed_on_demand
                     if report.apk_mode in ("manual", "partial") else frozenset())
            telemetry.record("repair", lambda p: repair_event(plan.device, session, plan.plans,
                                                              verdicts, result, interrupted, p,
                                                              blind=blind, actions=actions))

        return {"job_id": self._jobs.start("exec", run)}

    def _order_adb(self, number: str) -> tuple[Order, AdbTransport, DeviceInfo]:
        with self._journal() as journal:
            order = journal.order_by_number(number)
        if order is None:
            raise AppError("unknown_order", number)
        if self._adb is not None and self._serial == order.device_serial:
            adb: AdbTransport = self._adb
        else:
            ready = {e.serial for e in list_devices(self._host) if e.state == "device"}
            if order.device_serial not in ready:
                with self._journal() as journal:
                    name, imei = device_identity(journal, order.device_serial)
                raise AppError("wrong_device", order.device_serial, serial=order.device_serial,
                               device=name, imei=imei)
            adb = self._session(order.device_serial)
        device = read_device_info(adb)
        if same_device(order.device_identity, device) is False:
            # Ten sam numer seryjny, inny telefon (albo ten po przywróceniu ustawień fabrycznych):
            # kroki zlecenia nie mogą trafić na ten telefon (przegląd 2026-10-11).
            identity = order.device_identity or {}
            raise AppError("device_mismatch", order.device_serial, serial=order.device_serial,
                           device=order.device_model or order.device_serial,
                           imei=identity.get("imei"))
        return order, adb, device

    @_api
    def resume(self, number: str) -> dict[str, Any]:
        self._require_current()
        order, adb, device = self._order_adb(number)
        self._require_cleaned(order.device_serial)
        with self._journal() as journal:
            if not any(a.status == "pending" for a in journal.actions(order.id)):
                raise AppError("nothing_to_resume", number)
        self._abandon_apk()
        names = self._names()

        def run(job: Job) -> None:
            manufacturer = device.manufacturer
            with self._journal() as journal:
                self._bind_order(journal, order.device_serial, order.id)
                self._emit("exec:order", {"order": order.number, "plan": None})
                self._run_order(job, adb, journal, journal.order(order.id), manufacturer, names,
                                resume_steps)

        return {"job_id": self._jobs.start("resume", run)}

    @_api
    def undo(self, number: str, action_id: int | None = None,
             package: str | None = None) -> dict[str, Any]:
        order, adb, device = self._order_adb(number)
        self._require_cleaned(order.device_serial)
        with self._journal() as journal:
            targeted = targeted_actions(journal, order.id, package, action_id)
        if not targeted:
            raise AppError("no_target", number)
        self._abandon_apk()
        names = self._names()

        def run(job: Job) -> None:
            manufacturer = device.manufacturer
            with self._journal() as journal:
                try:
                    result = undo_order(adb, journal, order, package=package, action_id=action_id,
                                        options=self._options(job, manufacturer, names, journal,
                                                              order.number))
                except OrderInterrupted as exc:
                    self._emit("exec:disconnected", {"order": exc.order.number})
                    return
                restored = []
                for restored_id in result.restored_sites:
                    row = journal.action(restored_id)
                    restored.append({
                        "action_id": restored_id, "package": row.package,
                        **self._site_view(journal, restored_id, names),
                        "url": site_url(Step.from_dict(row.step))})
            status = result.order.status
            self._emit("undo:done", {
                "order": order.number, "status": status,
                "status_label": order_status_label(status, self._lang),
                "errors": [error_text(key, self._lang, manufacturer) for _, key in result.errors],
                "admin_not_restored": result.admin_not_restored,
                "sites_total": result.sites_total, "sites_restored": result.sites_restored,
                "restored_sites": restored,
                "firefox_debugging": result.firefox_debugging,
                "interrupted": self._interrupted(device),
            })
            apps, failed = undo_targets(targeted, result.errors)
            # Wiek liczony w `build`: ewentualny wyjątek łapie `record`, nie zadanie cofania.
            telemetry.record("undo", lambda p: undo_event(
                device, apps, failed, (self._now() - order.created_at).days, p,
                sites=result.sites_total, sites_restored=result.sites_restored))

        return {"job_id": self._jobs.start("undo", run)}

    @_api
    def apk_cache(self) -> dict[str, Any]:
        path = default_cache_dir()
        return {**asdict(usage(path, self._cache_limit())), "path": str(path)}

    @_api
    def clear_apk_cache(self) -> dict[str, Any]:
        job = self._jobs.current()
        if job is not None:  # analiza APK albo zlecenie, które może właśnie pobierać kopię
            raise AppError("busy", job.kind)
        return {"freed_bytes": clear_cache(default_cache_dir())}

    @_api
    def reopen_screen(self) -> dict[str, Any]:
        """„Otwórz ponownie na telefonie”: ekran, na który czeka zlecenie (kanał witryny, administrator),
        otwiera się znowu przy następnym sprawdzeniu stanu. Bez zlecenia w toku nic się nie dzieje."""
        if self._order_in_progress() is None:
            return {"ok": False}
        self._reopen.set()
        return {"ok": True}

    @_api
    def skip_site(self) -> dict[str, Any]:
        """„Pomiń” przy witrynie w cofaniu: bieżący ekran kanału przestaje czekać, następny się otwiera.
        Naprawa ma własne pytanie po upływie czasu, więc poza cofaniem nic się nie dzieje."""
        job = self._jobs.current()
        if job is None or job.kind != "undo":
            return {"ok": False}
        self._skip.set()
        return {"ok": True}

    @_api
    def open_site(self, number: str, action_id: int) -> dict[str, Any]:
        """Otwiera na telefonie witrynę przywróconego kanału, by zapisała się od nowa. Tylko między
        zadaniami (telefon nie jest wtedy zajęty ekranem kanału)."""
        job = self._jobs.current()
        if job is not None:
            raise AppError("busy", job.kind)
        order, adb, _device = self._order_adb(number)
        with self._journal() as journal:
            try:
                row = journal.action(action_id)
            except KeyError:
                return {"ok": False}
        step = Step.from_dict(row.step)
        if row.order_id != order.id or site_url(step) is None:
            return {"ok": False}
        try:
            return {"ok": open_site_on_phone(adb, step)}
        except ActionError:
            return {"ok": False}

    @_api
    def stop(self, job_id: str) -> dict[str, Any]:
        return {"ok": self._jobs.stop(job_id)}

    @_api
    def answer(self, job_id: str, value: str) -> dict[str, Any]:
        return {"ok": self._jobs.answer(job_id, value)}

    # --- przenoszenie danych: kopia starego telefonu ---------------------------------------------

    @_api
    def transfer_inventory(self, serial: str, client: str | None = None) -> dict[str, Any]:
        """Co da się skopiować ze starego telefonu: skan aplikacji (bez analizy APK) i inwentarz.

        Stan skanu naprawy (`_report`, `_adb`) zostaje nietknięty — to osobny przebieg."""
        if not isinstance(serial, str) or not serial.strip():
            raise AppError("bad_request", "serial")
        if client is not None and not isinstance(client, str):
            raise AppError("bad_request", "client")
        self._require_explorer_free(serial)
        self._require_cleaned(serial)
        self._abandon_apk(notify=False)
        adb = self._session(serial.strip())
        name = (client or "").strip() or None
        crash.note_names([name])

        def run(job: Job) -> None:
            with _transfer_errors("transfer_scan"):
                scan(job)

        def scan(job: Job) -> None:
            device = read_device_info(adb)
            crash.note_device(device.serial, device.manufacturer, device.model, device.android_release)
            match = self._provider.match(device)
            self._remember(device, match)
            self._emit("scan:device", {"device": device_card(device, match)})
            report = run_scan(adb, device=device)
            job.check()
            try:
                inventory = build_inventory(ReadOnlyAdb(adb), report, job.should_stop)
            except TransferStopped:
                raise Stopped from None
            job.check()
            self._publish_inventory(device, inventory, name)

        return {"job_id": self._jobs.start("transfer_scan", run)}

    def _publish_inventory(self, device: DeviceInfo, inventory: Inventory, name: str | None) -> None:
        self._transfer = (device, inventory, name)
        resumable = store.find_resumable(device.serial)
        self._emit("transfer:inventory", {
            "inventory": inventory_view(inventory, self._lang),
            "resumable": self._copy_view(resumable.read_meta()) if resumable else None,
            "client": name})

    @_api
    def transfer_rescan(self) -> dict[str, Any]:
        """Ponowny odczyt telefonu (serwisant nadał uprawnienie albo skopiował plik eksportu):
        aplikacje zostają z poprzedniego skanu, reszta inwentarza jest czytana od nowa."""
        device, previous, name = self._transfer_state()
        self._require_cleaned(device.serial)
        adb = self._session(device.serial)

        def run(job: Job) -> None:
            with _transfer_errors("transfer_scan"):
                try:
                    inventory = refresh_inventory(ReadOnlyAdb(adb), previous, job.should_stop)
                except TransferStopped:
                    raise Stopped from None
                job.check()
                self._publish_inventory(device, inventory, name)

        return {"job_id": self._jobs.start("transfer_scan", run)}

    def _transfer_state(self) -> tuple[DeviceInfo, Inventory, str | None]:
        """Inwentarz bieżącego telefonu; bez niego (albo gdy tego telefonu już nie ma) — odmowa."""
        state = self._transfer
        if state is None:
            raise AppError("transfer_no_inventory")
        ready = {e.serial for e in list_devices(self._host) if e.state == "device"}
        if state[0].serial not in ready:
            raise AppError("transfer_no_inventory", state[0].serial)
        return state

    @_api
    def transfer_whatsapp(self) -> dict[str, Any]:
        """Ponowny odczyt czasu kopii czatów WhatsApp (serwisant zrobił ją właśnie na telefonie)."""
        device, inventory, _client = self._transfer_state()
        when = whatsapp_backup_time(ReadOnlyAdb(self._session(device.serial)))
        inventory.whatsapp_backup = when
        return {"whatsapp_backup": when.isoformat(timespec="seconds") if when else None}

    @_api
    def start_backup(self, selection: dict[str, Any]) -> dict[str, Any]:
        """Kopia wybranych danych na komputer. Niedokończona kopia tego telefonu jest wznawiana."""
        device, inventory, client = self._transfer_state()
        chosen = _selection(selection, inventory)
        serial = device.serial
        self._require_cleaned(serial)
        self._abandon_apk()
        adb = self._session(serial)
        raw = self._host.with_serial(serial)  # odpytywanie `get-state` bez wpisu w logu co sekundę

        def run(job: Job) -> None:
            self._backup_serial = serial
            try:
                with _transfer_errors("backup"), device_lock(journal_path(), serial):
                    result, copy = self._run_backup(job, adb, raw, device, inventory, client, chosen)
            finally:
                self._backup_serial = None
            self._emit("transfer:done", {"result": backup_result_view(result),
                                         "copy": self._copy_view(copy.read_meta())})
            telemetry.record("transfer_backup",
                             lambda _packages: transfer_backup_event(device, result, chosen))

        return {"job_id": self._jobs.start("backup", run)}

    def _run_backup(self, job: Job, adb: SessionLogAdb, raw: AdbTransport, device: DeviceInfo,
                    inventory: Inventory, client: str | None,
                    chosen: Selection) -> tuple[BackupResult, store.CopyDir]:
        copy = store.find_resumable(device.serial) or store.create_copy(
            device.serial, device, client, self._now())
        # Id kopii od razu: serwisant może dopisać notatkę jeszcze w czasie kopiowania.
        self._emit("transfer:copy", {"copy": self._copy_view(copy.read_meta())})
        puller = self._puller_factory(self._settings.adb_path, device.serial, adb.tagged("pull"))
        progress, wait_device = self._transfer_events(job, raw, "transfer:progress")
        # Surowy transport (z logiem sesji), nie `ReadOnlyAdb`: silnik opakowuje go sam.
        result = run_backup(adb, puller, device, copy, inventory, chosen, on_progress=progress,
                            should_stop=job.should_stop, wait_device=wait_device, now=self._now())

        return result, copy

    def _transfer_events(self, job: Job, raw: AdbTransport, event: str,
                         ) -> tuple[Callable[[Progress | RestoreProgress | TelProgress], None],
                                    Callable[[], None]]:
        """(`on_progress`, `wait_device`) dla silnika kopii, wgrywania i telefonii. Postęp idzie
        zdarzeniem `event`, dławiony do jednego na `TRANSFER_PROGRESS_S` w obrębie etapu (telefonia:
        kategorii; nowy etap — od razu). `wait_device` odpytuje `get-state` surowym transportem (`raw`,
        bez wpisu w logu co sekundę) i raz wysyła `transfer:waiting`."""
        last: dict[str, Any] = {"at": None, "stage": None, "p": None}

        def progress(p: Progress | RestoreProgress | TelProgress) -> None:
            last["p"] = p
            now = time.monotonic()
            stage = p.kind if isinstance(p, TelProgress) else p.stage
            if (last["stage"] == stage and last["at"] is not None
                    and now - last["at"] < TRANSFER_PROGRESS_S):
                return
            last["at"], last["stage"] = now, stage
            self._emit(event, asdict(p))

        def wait_device() -> None:
            # Zatrzymanie w czasie czekania: wracamy, a silnik sam kończy przebieg wynikiem
            # „stopped” (jak zatrzymanie w trakcie przebiegu) — z wynikiem i statystyką.
            waiting = False
            while not job.should_stop():
                try:
                    if raw.run(["get-state"]).strip() == "device":
                        if waiting and last["p"] is not None:
                            # telefon wrócił: UI chowa „Telefon odłączony” od razu, nie dopiero
                            # przy następnym postępie (eksport telefonii trwa minuty)
                            self._emit(event, asdict(last["p"]))
                        return
                except AdbError:
                    pass
                if not waiting:
                    waiting = True
                    self._emit("transfer:waiting", {})
                time.sleep(self._poll_interval)

        return progress, wait_device

    # --- przenoszenie danych: wgrywanie kopii na nowy telefon -------------------------------------

    @_api
    def restore_plan(self, copy_id: str, serial: str) -> dict[str, Any]:
        """Plan wgrywania kopii na telefon `serial`: co już jest, co trafi obok jako „(z kopii)”,
        ocena APK i miejsce, a dla telefonii (`tel`) — ile kontaktów, wiadomości i połączeń telefon
        jeszcze potrzebuje. Na telefon idą tylko odczyty (`AppendOnlyAdb`, `TelPlanReadAdb`); stan
        wgrywania tej kopii na ten telefon (jeśli jest) daje cele własnych niedokończonych plików."""
        if not isinstance(copy_id, str):
            raise AppError("bad_request", "copy_id")
        if not isinstance(serial, str) or not serial.strip():
            raise AppError("bad_request", "serial")
        try:
            copy = store.copy_dir(copy_id)
            meta = copy.read_meta()
        except (OSError, ValueError, KeyError, TypeError):  # ścieżka nie idzie do raportu
            raise AppError("bad_request", "copy_id") from None
        if meta.status == "in_progress":  # wgrywać można tylko kopię skończoną (spec §4.1)
            raise AppError("bad_request", "copy_status")
        self._require_explorer_free(serial)
        self._require_cleaned(serial)
        self._abandon_apk(notify=False)
        adb = self._session(serial.strip())

        def run(job: Job) -> None:
            self._restore = None  # nieudany plan nie zostawia poprzedniego (innej kopii albo telefonu)
            self._restore_copy_id = copy_id
            try:
                with _transfer_errors("restore_plan"):
                    device, plan, tel_plan = plan_on(job)
                    view = self._copy_view(copy.read_meta())  # kopia zniknęła → błąd kopii
            finally:
                self._restore_copy_id = None
            self._restore = (device, copy, plan, tel_plan)
            mine = next((r for r in read_restores(copy) if r.serial == device.serial), None)
            self._emit("transfer:restore_plan", {
                "plan": restore_plan_view(plan),
                "tel": tel_plan_view(tel_plan),
                "copy": view,
                "resumable": mine is not None and mine.resumable,
                "same_phone_recent": (meta.serial == device.serial
                                      and self._now() - meta.created < SAME_PHONE_RECENT)})

        def plan_on(job: Job) -> tuple[DeviceInfo, RestorePlan, TelPlan]:
            device = read_device_info(adb)
            crash.note_device(device.serial, device.manufacturer, device.model, device.android_release)
            match = self._provider.match(device)
            self._remember(device, match)
            self._emit("scan:device", {"device": device_card(device, match)})
            taken = None
            path = restore_state_path(copy, device.serial)
            if path.is_file():  # sam plan nie zakłada stanu wgrywania
                state = RestoreState(path)
                try:
                    taken = state.taken_alts()
                finally:
                    state.close()
            try:
                plan = build_plan(AppendOnlyAdb(adb), copy, job.should_stop, taken_alts=taken)
            except TransferStopped:
                raise Stopped from None
            job.check()
            # Telefonia: same odczyty (`content query` przez strażnika odczytu + `dumpsys account`);
            # zapis przez `TelephonyWriteAdb` dopiero przy wgrywaniu.
            tel_plan = build_tel_plan(TelPlanReadAdb(adb), copy, meta, set(TEL_CATEGORIES))
            job.check()
            # przerwane wgrywanie, w którym telefon ma już wszystko: zamykamy stan, żeby Banner wznowienia zniknął
            settle_finished(copy, device.serial, plan, tel_plan, AppendOnlyAdb(adb), device.sdk)
            return device, plan, tel_plan

        return {"job_id": self._jobs.start("restore_plan", run)}

    @_api
    def start_restore(self, choice: dict[str, Any]) -> dict[str, Any]:
        """Wgrywanie wybranych plików kopii na nowy telefon z ostatniego planu. Przerwane wgrywanie
        tej kopii na ten telefon jest wznawiane (stan w katalogu kopii)."""
        state = self._restore
        if state is None:
            raise AppError("transfer_no_plan")
        device, copy, plan, tel_plan = state
        serial = device.serial
        if serial not in {e.serial for e in list_devices(self._host) if e.state == "device"}:
            raise AppError("transfer_no_plan", serial)
        chosen = _upload_choice(choice, plan)
        self._require_cleaned(serial)
        copy_id = f"{copy.path.parent.name}/{copy.path.name}"
        self._abandon_apk()
        adb = self._session(serial)
        raw = self._host.with_serial(serial)  # odpytywanie `get-state` bez wpisu w logu co sekundę

        def run(job: Job) -> None:
            self._restore_copy_id = copy_id
            tel: TelResult | None = None
            tel_error: str | None = None
            try:
                with _transfer_errors("restore"), device_lock(journal_path(), serial):
                    if chosen.tel:
                        self._note_tel_pending(copy, serial, tel_plan, chosen.tel)
                    result = self._run_restore(job, adb, raw, device, copy, plan, chosen)
                    if chosen.tel and result.status != "stopped":  # zatrzymane pliki: telefonia czeka
                        try:
                            with _transfer_errors("restore_tel"):
                                tel = self._run_tel(job, adb, raw, device, copy, tel_plan, chosen.tel)
                        except Stopped:
                            raise
                        except Exception as exc:  # noqa: BLE001 — pliki już są: ich wynik idzie dalej
                            tel_error = error_payload(exc)["key"]
                    view = self._copy_view(copy.read_meta())  # kopia zniknęła → błąd kopii
            finally:
                self._restore_copy_id = None
                with self._cleanup_lock:
                    self._cleaned.discard(serial)  # nieudane przywrócenie telefonu: sprzątanie zaraz po zadaniu
                    self._cleanup_tries.pop(serial, None)  # nowe zmiany telefonu: od nowa pełne ponowienia
            self._emit("transfer:restore_done", {"result": restore_result_view(result), "copy": view,
                                                 "tel": tel_result_view(tel) if tel is not None else None,
                                                 "tel_error": tel_error})
            failed = tel_error is not None
            telemetry.record("transfer_restore", lambda _packages: transfer_restore_event(
                device, result, chosen, STREAMS, tel, tel_failed=failed))

        return {"job_id": self._jobs.start("restore", run)}

    def _note_tel_pending(self, copy: store.CopyDir, serial: str, tel_plan: TelPlan,
                          kinds: frozenset[str]) -> None:
        """Przed plikami: rekordy wybranej telefonii w `tel_left`, żeby program zamknięty po plikach
        (stan `complete`), a przed telefonią zostawił Banner wznowienia. Przebieg telefonii nadpisuje
        tę liczbę swoją kolejką, a na końcu wynikiem. Kopii usuniętej w międzyczasie nie odtwarzamy
        (stan założyłby jej katalog na nowo) — wgrywanie i tak skończy się `copy_missing`."""
        left = sum(tel_records_to_write(tel_plan, kinds).values())
        if not left or not copy.files_dir.is_dir():
            return
        state = RestoreState(restore_state_path(copy, serial))
        try:
            state.set_meta("tel_left", left)
        finally:
            state.close()

    def _run_restore(self, job: Job, adb: SessionLogAdb, raw: AdbTransport, device: DeviceInfo,
                     copy: store.CopyDir, plan: RestorePlan, chosen: UploadChoice) -> RestoreResult:
        pusher = self._pusher_factory(self._settings.adb_path, device.serial, adb.tagged("push"))
        progress, wait_device = self._transfer_events(job, raw, "transfer:restore_progress")
        return run_restore(AppendOnlyAdb(adb), pusher, device, copy, plan, chosen, on_progress=progress,
                           should_stop=job.should_stop, wait_device=wait_device, streams=STREAMS)

    def _run_tel(self, job: Job, adb: SessionLogAdb, raw: AdbTransport, device: DeviceInfo,
                 copy: store.CopyDir, tel_plan: TelPlan, kinds: frozenset[str]) -> TelResult:
        """Kontakty, wiadomości i połączenia po plikach. Odczyty (kopia bezpieczeństwa, klucze, widoczność)
        przez strażnika odczytu; zmiany telefonu i zapisy przez `TelephonyWriteAdb` z rolą SMS oddawaną
        tylko zapisanemu poprzedniemu posiadaczowi. Postęp: `transfer:tel_progress`."""
        pusher = self._pusher_factory(self._settings.adb_path, device.serial, adb.tagged("push"))
        progress, wait_device = self._transfer_events(job, raw, "transfer:tel_progress")
        wanted = engine_tel_kinds(kinds)  # `sms` z ekranu obejmuje MMS (silnik: osobno)
        state = RestoreState(restore_state_path(copy, device.serial))
        try:
            return run_tel_restore(
                telephony_adb(adb, state), ReadOnlyAdb(adb), pusher, device, copy, tel_plan, wanted,
                state, on_progress=progress, should_stop=job.should_stop, wait_device=wait_device,
                on_tap=self._tap_handler(state), skip_tap=self._skip_tap.is_set)
        finally:
            self._end_tap()
            state.close()

    @_api
    def skip_tap(self) -> dict[str, Any]:
        """„Pomiń” przy prośbie o domyślną aplikację SMS: wiadomości pójdą do pliku do ręcznego importu.
        Oddania roli poprzedniej aplikacji pominąć nie wolno (telefon zostałby z naszą aplikacją SMS)."""
        request = self._tap_request
        if request == "sms_role_restore":
            raise AppError("bad_request", "restore_required")
        if request != "sms_role_grant":
            raise AppError("bad_request", "no_tap")
        self._skip_tap.set()
        return {}

    @_api
    def transfers(self) -> dict[str, Any]:
        self._purge_transfers()
        now = self._now()
        restoring = self._restoring()
        return {"copies": [self._copy_view(m, now, restoring) for m in store.list_copies()]}

    @_api
    def extend_transfer(self, copy_id: str) -> dict[str, Any]:
        if not isinstance(copy_id, str):
            raise AppError("bad_request", "copy_id")
        try:
            meta = store.extend(copy_id)
        except OSError:  # meta.json zablokowany przez inny program; ścieżka nie idzie do raportu
            raise AppError("transfer_in_use") from None
        return {"copy": self._copy_view(meta)}

    @_api
    def set_transfer_note(self, copy_id: str, note: str | None) -> dict[str, Any]:
        """Notatka serwisanta do kopii — w Historii i w czasie kopiowania (`transfer:copy` daje id)."""
        if not isinstance(copy_id, str):
            raise AppError("bad_request", "copy_id")
        if note is not None and (not isinstance(note, str) or len(note.strip()) > store.NOTE_MAX):
            raise AppError("bad_request", "note")
        try:
            meta = store.set_note(copy_id, note)
        except OSError:  # note.txt zablokowany przez inny program; ścieżka nie idzie do raportu
            raise AppError("transfer_in_use") from None
        return {"copy": self._copy_view(meta)}

    @_api
    def delete_transfer(self, copy_id: str) -> dict[str, Any]:
        if not isinstance(copy_id, str):
            raise AppError("bad_request", "copy_id")
        if self._copy_busy(copy_id):
            raise AppError("busy", "restore")
        meta = next((m for m in store.list_copies() if m.id == copy_id), None)
        if meta is not None and self._transfer_busy(meta.serial):
            raise AppError("busy", "backup")
        try:
            store.delete(copy_id)  # zmiany nowego telefonu zostają w zapisie telefonu poza kopią
        except OSError:  # plik kopii otwarty w innym programie; ścieżka nie idzie do raportu
            raise AppError("transfer_in_use") from None
        return {"deleted": copy_id}

    # --- aktualizacje ---------------------------------------------------------------------------

    @_api
    def update_state(self) -> dict[str, Any]:
        return self._update_view()

    @_api
    def dismiss_update(self, version: str) -> dict[str, Any]:
        if not isinstance(version, str) or not version.strip():
            raise AppError("bad_request", "version")
        self._settings = save_settings({"dismissed_update": version})
        return self._update_view()

    @_api
    def install_update(self) -> dict[str, Any]:
        st = self._updates.state()
        if not st.available or st.manifest is None:
            raise AppError("update_none")
        manifest = st.manifest
        page = update.download_page(self._lang)
        if not self._frozen:
            self._open_url(page)  # wersja deweloperska: bez instalatora na drzewie źródeł
            return {"opened": True}

        last = {"done": 0, "at": None}  # dławienie: ~1600 wywołań run_js na 100 MB to za dużo

        def progress(done: int, total: int | None) -> None:
            now = time.monotonic()
            final = total is not None and done >= total
            step = max(total // 100, 1) if total else 1 << 20
            if not (final or last["at"] is None or done - last["done"] >= step
                    or now - last["at"] >= 0.25):
                return
            last["done"], last["at"] = done, now
            self._emit("update:progress", {"done": done, "total": total})

        def run(job: Job) -> None:
            try:
                setup = self._update_download(manifest, progress, job.should_stop)
            except client.Cancelled:
                raise Stopped from None
            except installer.Corrupt:
                raise AppError("update_corrupt") from None
            except (client.BackendError, OSError) as exc:  # sieć albo dysk
                raise AppError("update_download", str(exc)) from None
            try:
                self._launch_setup(setup)
            except OSError as exc:
                raise AppError("update_launch_failed", str(exc), page=page) from None
            self.quit()  # instalator czeka na zamknięcie AdMeNot.exe (CloseApplications=force)

        return {"job_id": self._jobs.start("update", run)}

    # --- raporty błędów (spec raportów błędów §5.1) -----------------------------------------

    @staticmethod
    def _crash_errors(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return fn()
        except crash.UnknownCrash:
            raise AppError("unknown_crash") from None
        except BackendError as exc:
            if exc.kind == "offline" or exc.status in (429, 503):
                raise AppError("crash_offline", str(exc)) from None
            raise AppError("crash_rejected", str(exc)) from None

    @staticmethod
    def _crash_comment(comment: Any) -> str | None:
        if comment is not None and not isinstance(comment, str):
            raise AppError("bad_request", "comment")
        return comment

    @_api
    def capture_ui_error(self, message: str, stack: str | None = None,
                         screen: str | None = None) -> dict[str, Any]:
        if not isinstance(message, str):
            raise AppError("bad_request", "message")
        crash_id = crash.capture(kind="ui", type_="UIError", message=message,
                                 trace=stack if isinstance(stack, str) else None,
                                 where=message[:120],
                                 context={"screen": screen if isinstance(screen, str) else None})
        return {"crash": crash_id}

    @_api
    def crash_reports(self) -> dict[str, Any]:
        return {"reports": crash.list_reports(), "startup": crash.startup_reports()}

    @_api
    def crash_preview(self, crash_id: str, include_adb: bool = False,
                      comment: str | None = None) -> dict[str, Any]:
        text = self._crash_comment(comment)
        return self._crash_errors(lambda: crash.preview(crash_id, include_adb is True, text))

    @_api
    def send_crash(self, crash_id: str, include_adb: bool = False,
                   comment: str | None = None) -> dict[str, Any]:
        text = self._crash_comment(comment)
        return self._crash_errors(
            lambda: {"sent_id": crash.send(crash_id, include_adb is True, text)})

    @_api
    def discard_crash(self, crash_id: str) -> dict[str, Any]:
        return self._crash_errors(lambda: crash.discard(crash_id) or {})

    # --- historia ------------------------------------------------------------------------------

    @_api
    def history(self, serial: str | None = None) -> dict[str, Any]:
        with self._journal() as journal:
            serials = journal.recent_serials()
            chosen = serial or self._serial or (serials[0] if serials else None)
            return history_view(journal, chosen, serials, self._lang)

    @_api
    def delete_order(self, number: str) -> dict[str, Any]:
        """Zlecenie razem z jego zrzutami, protokołem i kopiami APK (RODO, przegląd 2026-10-11)."""
        if not isinstance(number, str) or not number.strip():
            raise AppError("bad_request", "order")
        job = self._jobs.current()
        if job is not None:
            raise AppError("busy", job.kind)
        number = number.strip()
        with self._journal() as journal:
            order = journal.order_by_number(number)
            if order is None:
                raise AppError("unknown_order", number)
            with device_lock(journal.path, order.device_serial):
                retention.delete_order(journal, order)
        with self._shots_lock:
            self._open_order = {s: o for s, o in self._open_order.items() if o != order.id}
        return {"deleted": number}

    # --- protokół i dane serwisu (Plan 6, spec §9.3) ----------------------------------------

    @_api
    def report(self, order: str) -> dict[str, Any]:
        if not isinstance(order, str) or not order.strip():
            raise AppError("bad_request", "order")
        number = order.strip()
        if not self._report_lock.acquire(blocking=False):
            raise AppError("busy", "report")
        try:
            files = write_report(number, self._lang, now=self._now)
        except UnknownOrder:
            raise AppError("unknown_order", number) from None
        finally:
            self._report_lock.release()
        target = files.pdf or files.html
        try:
            self._open_file(target)
            opened: str | None = str(target)
        except OSError:  # brak programu do PDF/HTML: plik jest zapisany, UI poda jego ścieżkę
            opened = None
        return {"order": number, "html": str(files.html),
                "pdf": str(files.pdf) if files.pdf else None,
                "pdf_target": str(files.pdf_target) if files.pdf_target else None,
                "error": files.pdf_error, "opened": opened}

    @_api
    def service(self) -> dict[str, Any]:
        return _service_view(load_service())

    @_api
    def save_service(self, changes: dict[str, Any]) -> dict[str, Any]:
        changes = dict(changes)
        unknown = sorted(set(changes) - set(SERVICE_KEYS))
        if unknown:
            raise AppError("bad_request", ", ".join(unknown))
        info = load_service()
        values: dict[str, Any] = {}
        for key in ("name", "address", "phone"):
            if key in changes:
                value = changes[key]
                values[key] = (value.strip() or None) if isinstance(value, str) else None
        if "logo" in changes:
            raw = changes["logo"]
            if not (isinstance(raw, str) and raw.strip()):
                values["logo"] = None
            elif info.logo is not None and Path(raw) == info.logo:
                pass  # okno odsyła zapisaną ścieżkę; plik mógł zniknąć — to nie blokuje innych zmian
            else:
                try:
                    values["logo"] = check_logo(Path(raw))
                except LogoError as exc:
                    raise AppError(f"logo_{exc.key}", str(raw)) from None
        info = replace(info, **values)
        save_service(info)
        return _service_view(info)

    @_api
    def pick_logo(self) -> dict[str, Any]:
        return {"path": self._pick_file_fn() if self._pick_file_fn else None}

    # --- konsola, adb, okno --------------------------------------------------------------------

    @_api
    def adb_shell(self, command: str) -> dict[str, Any]:
        command = (command or "").strip()
        if not command:
            raise AppError("bad_request", "command")
        if self._adb is None:
            raise AppError("no_device")
        job = self._order_in_progress()
        if job is not None:
            raise AppError("busy", job.kind)
        try:
            output = self._adb.tagged("console").shell(command, timeout=CONSOLE_TIMEOUT)
        except AdbError as exc:
            return {"ok": False, "output": exc.message}
        return {"ok": True, "output": output}

    @_api
    def check_adb(self, path: str | None = None) -> dict[str, Any]:
        tool = resolve_adb(path or None)
        try:
            out = self._host_factory(path or None).run(["version"])
        except AdbError as exc:
            return {"ok": False, "version": None, "message": exc.message,
                    "source": tool.source, "path": tool.path}
        lines = out.strip().splitlines()
        return {"ok": True, "version": lines[0] if lines else "", "message": "",
                "source": tool.source, "path": tool.path}

    @_api
    def pick_folder(self) -> dict[str, Any]:
        return {"path": self._pick_folder_fn() if self._pick_folder_fn else None}

    def _attach(self, pick_folder: Callable[[], str | None], close: Callable[[], None],
                pick_file: Callable[[], str | None] | None = None,
                pick_files: Callable[[], list[str]] | None = None) -> None:
        self._pick_folder_fn = pick_folder
        self._close_fn = close
        self._pick_file_fn = pick_file
        self._pick_files_fn = pick_files  # eksplorator: „Wgraj tutaj” (wiele plików)

    def _transfer_job(self) -> Job | None:
        job = self._jobs.current()
        return job if job is not None and job.kind in TRANSFER_KINDS else None

    def _shutdown(self) -> None:
        self._purge_stop.set()
        try:
            self._explorer_end()
        except Exception as exc:  # noqa: BLE001 — zamknięcie okna nie może utknąć na eksploratorze
            log_exception(exc)
        job = self._transfer_job()
        if job is not None:
            self._jobs.stop(job.id)  # bez czekania: `_shutdown` bywa wołane z wątku GUI
        self._updates.stop()
        self._mirror.stop()
        self._watcher.stop()
        self._abandon_apk()
        if self._labels is not None:
            self._labels.cancel()

    def _on_closing(self) -> bool:
        if self._quitting:
            return True
        job = self._order_in_progress()
        if job is not None:
            # `closing` biegnie na wątku GUI, a `run_js` czeka na ten sam wątek (zakleszczenie),
            # więc zdarzenie wysyła osobny wątek, a okno od razu dostaje odpowiedź.
            threading.Thread(target=self._emit, args=("app:close_requested", {"kind": job.kind}),
                             daemon=True).start()
            return False
        job = self._transfer_job()
        if job is not None:
            # Kopia się wznowi, więc nie pytamy — tylko zatrzymujemy ją porządnie (zabity `adb pull`,
            # stan zapisany) i zamykamy okno po jej końcu. Nigdy nie czekamy na wątku GUI: zdarzenia
            # zadania (`run_js`) czekają na ten sam wątek.
            self._jobs.stop(job.id)
            threading.Thread(target=self._close_after, args=(job,), daemon=True,
                             name="admenot-quit").start()
            return False
        if self._explorer_active():
            # Jak przy kopii: bez pytania (UI pyta przy wyjściu z eksploratora, okno zamyka serwisant),
            # zadania eksploratora są anulowane, a okno zamyka się dopiero po końcu wątku kolejki (zabity
            # `adb`, usunięte `.admenot-part`) — na osobnym wątku, nigdy na wątku GUI.
            threading.Thread(target=self._close, daemon=True, name="admenot-quit").start()
            return False
        self._shutdown()
        return True

    @_api
    def quit(self) -> dict[str, Any]:
        job = self._order_in_progress() or self._transfer_job()
        if job is not None:
            self._jobs.stop(job.id)
            if not job.done.wait(QUIT_WAIT):
                # Bieżący krok (np. instalacja z kopii, do INSTALL_TIMEOUT) jeszcze trwa: zamykamy
                # dopiero po nim, bez zrywania ADB w połowie (audyt 2026-10-11, EDGE-01).
                threading.Thread(target=self._close_after, args=(job,), daemon=True,
                                 name="admenot-quit").start()
                return {"ok": True, "closing_after_step": True}
        self._close()
        return {"ok": True}

    def _close_after(self, job: Job) -> None:
        job.done.wait()
        self._close()

    def _close(self) -> None:
        """Zamknięcie programu poza wątkiem GUI (`quit`, `_close_after`, `_on_closing` z zadaniami
        eksploratora): najpierw czeka na koniec kolejki eksploratora, potem reszta `_shutdown`."""
        self._explorer_quit()
        self._shutdown()
        self._quitting = True
        if self._close_fn is not None:
            self._close_fn()
