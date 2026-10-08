"""Most GUI <-> silnik (spec §3.2): metody dla `window.pywebview.api`, zdarzenia `admenot:*`.

pywebview wystawia do JS publiczne metody i atrybuty — cały stan trzymamy w polach `_…`.
Każda publiczna metoda zwraca słownik JSON; błąd to `{"error": {"key", "message", …}}`.
Długie operacje (skan, analiza APK, wykonanie, wznowienie, cofnięcie) idą przez `JobRunner`
i od razu zwracają `{"job_id"}`; postęp przychodzi zdarzeniami.
Protokół i dane serwisu nie dotykają telefonu, więc idą bez JobRunner (pywebview woła każdą metodę w osobnym wątku).
"""

from __future__ import annotations

import functools
import os
import sys
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from admenot import __version__
from admenot.app.errors import AppError, error_payload, log_exception, report_error
from admenot.app.events import Emitter
from admenot.app.jobs import Job, JobRunner, Stopped
from admenot.app.present import (
    app_name,
    device_card,
    device_identity,
    estimate_view,
    history_view,
    plan_view,
    result_view,
    scan_view,
    step_view,
)
from admenot.app.updates import UpdateService, update_view
from admenot.app.watcher import DeviceWatcher
from admenot.engine.actions.executor import ExecOptions, run_order
from admenot.engine.actions.executor import resume as resume_steps
from admenot.engine.adb.devices import list_devices
from admenot.engine.adb.sessionlog import SessionLogAdb, session_log_path
from admenot.engine.adb.transport import AdbError, AdbTransport, RealAdb
from admenot.engine.apk.cache import GB, CacheUsage, Estimate, clear_cache, disk_total, usage
from admenot.engine.apk.fetch import default_cache_dir
from admenot.engine.apk.providers import ApkProvider, CachePolicy, DeviceApkProvider
from admenot.engine.device.info import read_device_info
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
from admenot.engine.paths import incident_path, journal_path, logs_dir, screenshot_files
from admenot.engine.phones.provider import PhoneImageProvider, PhoneMatch
from admenot.engine.report.files import UnknownOrder, write_report
from admenot.engine.report.render import data_uri
from admenot.engine.screenshot import delete_shots, take_screenshot
from admenot.engine.session import ScanReport, analyze_apks, run_scan
from admenot.engine.settings import (
    LogoError,
    ServiceInfo,
    SettingsTooNew,
    check_logo,
    effective_lang,
    load_service,
    load_settings,
    save_service,
    save_settings,
)
from admenot.engine.texts import error_text, order_status_label, screenshot_caption
from admenot.engine.tools import resolve_adb
from admenot.engine.workflow import (
    OrderInterrupted,
    Runner,
    clear_cache_after_repair,
    execute_order,
    plan_order,
    start,
    targeted_actions,
    undo_order,
)
from admenot.net import client, installer, update

HostFactory = Callable[[str | None], AdbTransport]
ApkFactory = Callable[..., ApkProvider]

ADMIN_TIMEOUT = 180.0
ORDER_KINDS = frozenset({"exec", "resume", "undo"})
INCIDENT_MAX_S = 600.0  # nagranie incydentu: najwyżej 10 min
INCIDENT_INTERVAL_S = 2.0
CONSOLE_TIMEOUT = 30.0
QUIT_WAIT = 30.0


def _real_host(adb_path: str | None) -> AdbTransport:
    return RealAdb(adb_path=adb_path)


def _startfile(path: Path) -> None:
    os.startfile(path)  # type: ignore[attr-defined]  # tylko Windows


SERVICE_KEYS = ("name", "address", "phone", "logo")


def _service_view(info: ServiceInfo) -> dict[str, Any]:
    return {"name": info.name, "address": info.address, "phone": info.phone,
            "logo": str(info.logo) if info.logo else None}


def _api(method: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    @functools.wraps(method)
    def wrapper(self: Api, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — do JS nigdy nie leci wyjątek
            return {"error": report_error(exc)}

    return wrapper


class Api:
    def __init__(
        self,
        emitter: Emitter,
        host_factory: HostFactory = _real_host,
        provider: PhoneImageProvider | None = None,
        apk_factory: ApkFactory | None = DeviceApkProvider,
        *,
        sync_jobs: bool = False,
        admin_timeout: float = ADMIN_TIMEOUT,
        poll_interval: float = 1.0,
        now: Callable[[], datetime] = datetime.now,
        open_file: Callable[[Path], None] = _startfile,
        mirror_factory: Callable[..., Mirror] = Mirror,
        update_fetch: Callable[[], update.Manifest] = update.fetch,
        update_download: Callable[..., Path] = installer.download,
        launch_setup: Callable[[Path], object] = installer.launch,
        open_url: Callable[[str], object] = webbrowser.open,
        frozen: bool | None = None,
    ) -> None:
        self._emitter = emitter
        self._host_factory = host_factory
        self._provider = provider or PhoneImageProvider.default()
        self._apk_factory = apk_factory
        self._jobs = JobRunner(emitter, sync=sync_jobs)
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
        self._report: ScanReport | None = None
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
        self._identities: dict[str, tuple[str | None, str | None]] = {}  # telefon → (nazwa, IMEI)
        self._pending: dict[str, list[int]] = {}  # telefon → zrzuty czekające na zlecenie
        self._shots_lock = threading.Lock()  # chroni _open_order/_pending; nigdy pod adb/screencap
        self._clean_screenshots()
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

    def _abandon_apk(self) -> None:
        job = self._jobs.current()
        if job is not None and job.kind in ("apk", "deep"):
            self._jobs.abandon(job.id)

    def _order_in_progress(self) -> Job | None:
        job = self._jobs.current()
        return job if job is not None and job.kind in ORDER_KINDS else None

    def _require_scan(self) -> None:
        if self._report is None or self._adb is None:
            raise AppError("no_scan")

    def _interrupted(self, serial: str) -> list[str]:
        with self._journal() as journal:
            return [o.number for o in journal.interrupted_orders(serial)]

    def _note_version(self) -> str | None:
        """Wersja, do której program właśnie się zaktualizował — komunikat raz (spec §6.5)."""
        last = self._settings.last_run_version
        if last == __version__:
            return None
        try:
            self._settings = save_settings({"last_run_version": __version__})
        except SettingsTooNew:
            return None  # ustawień z nowszej wersji nie nadpisujemy
        return __version__ if last else None  # pierwsze uruchomienie to nie aktualizacja

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

    def _start_updates(self) -> None:
        """Tylko z `run_gui`: sprzątanie starych instalatorów i wątek sprawdzania."""
        installer.cleanup()
        self._updates.start()

    def _device_list(self) -> dict[str, Any]:
        try:
            entries = list_devices(self._host)
        except AdbError as exc:
            return {"devices": [], "error": error_payload(exc)["key"]}
        ready = {e.serial for e in entries if e.state == "device"}
        for serial in set(self._identities) - ready:
            self._identities.pop(serial, None)  # odłączony: przy następnym podłączeniu czytamy od nowa
        devices = []
        for e in entries:
            name, imei = self._identity(e.serial) if e.serial in ready else (None, None)
            devices.append({"serial": e.serial, "state": e.state, "model": e.model,
                            "name": name, "imei": imei})
        return {"devices": devices, "error": None}

    def _identity(self, serial: str) -> tuple[str | None, str | None]:
        """Nazwa handlowa i IMEI już na ekranie podłączenia — raz na podłączenie, nie co odpytanie."""
        if serial not in self._identities:
            try:
                device = read_device_info(self._session(serial))
            except AdbError:
                return None, None  # np. telefon jeszcze się nie odblokował: spróbujemy przy następnym
            self._identities[serial] = (device_card(device, self._provider.match(device))["name"],
                                        device.imei)
        return self._identities[serial]

    # --- ustawienia i telefony --------------------------------------------------------------

    @_api
    def get_settings(self) -> dict[str, Any]:
        return {**asdict(self._settings), "lang": self._lang}

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
        self._abandon_apk()
        with self._shots_lock:
            self._open_order.pop(serial.strip(), None)
        adb = self._session(serial.strip())
        name = (client or "").strip() or None

        def run(job: Job) -> None:
            self._emit("scan:stage", {"stage": "identify"})
            device = read_device_info(adb)
            match = self._provider.match(device)
            self._identities[device.serial] = (device_card(device, match)["name"], device.imei)
            self._adb, self._serial, self._client = adb, device.serial, name
            self._report, self._match = None, match
            self._emit("scan:device", {"device": device_card(device, match)})
            incidents = load_incident(incident_path(device.serial), self._now())
            report = run_scan(adb, device=device, incidents=incidents,
                              on_stage=lambda stage: self._emit("scan:stage", {"stage": stage}))
            job.check()
            self._report = report
            self._emit("scan:done", {"scan": scan_view(report, self._lang),
                                     "interrupted": self._interrupted(device.serial),
                                     "client": name})
            if self._apk_factory is not None:
                job.kind = "apk"
                self._run_apk(job, adb, report)

        return {"job_id": self._jobs.start("scan", run)}

    def _cache_limit(self) -> int:
        return self._settings.apk_cache_limit_gb * GB

    def _run_apk(self, job: Job, adb: AdbTransport, report: ScanReport,
                 deep: frozenset[str] = frozenset()) -> None:
        def decide(est: Estimate, use: CacheUsage) -> str:
            # Zatrzymanie zadania w trakcie pytania (None) = pominięcie; `job.check` niżej kończy.
            return job.ask("apk:question", {"kind": "no_space", **estimate_view(est, use)}) or "skip"

        policy = CachePolicy(self._cache_limit(),
                             on_estimate=lambda est, use: self._emit("apk:estimate",
                                                                     estimate_view(est, use)),
                             decide=decide)
        provider = self._apk_factory(adb, policy=policy, deep=deep)

        def progress(done: int, total: int, package: str) -> None:
            job.check()
            self._emit("apk:progress", {"done": done, "total": total, "package": package})

        try:
            updated = analyze_apks(report, provider, progress, only=deep or None)
            job.check()
        except Stopped:
            self._emit("apk:stopped", {})
            return
        self._report = updated
        self._emit("apk:done", {"scan": scan_view(updated, self._lang)})

    @_api
    def deep_analyze(self, package: str) -> dict[str, Any]:
        """Głęboka analiza jednej aplikacji (ścieżki w kodzie) — tylko na żądanie, ocena §6, §8."""
        self._require_scan()
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
                self._emit("incident:done", {"marks": 0, "hits": [], "error": report_error(exc)})
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
        return {r.facts.package: app_name(r.facts, r.facts.package) for r in self._report.results}

    def _options(self, job: Job, manufacturer: str, names: dict[str, str]) -> ExecOptions:
        def on_event(event: dict[str, Any]) -> None:
            kind = event["type"]
            if kind == "step":
                self._emit("exec:step", step_view(event, self._lang, manufacturer, names))
            elif kind == "undo":
                self._emit("undo:step", step_view(event, self._lang, manufacturer, names))
            elif kind == "admin_wait":
                package = event["package"]
                self._emit("exec:admin_wait", {"package": package,
                                               "name": names.get(package, package),
                                               "timeout": event["timeout"]})
            elif kind == "admin_done":
                self._emit("exec:admin_done", {"package": event["package"],
                                               "status": event["status"]})
            elif kind == "verify":
                self._emit("exec:verify", {})

        def on_admin_timeout(package: str) -> str:
            answer = job.ask("exec:question", {"kind": "admin_timeout", "package": package,
                                               "name": names.get(package, package)})
            return "retry" if answer == "retry" else "skip"

        return ExecOptions(apk_cache_dir=default_cache_dir(), admin_timeout=self._admin_timeout,
                           poll_interval=self._poll_interval, on_event=on_event,
                           on_admin_timeout=on_admin_timeout, should_stop=job.should_stop)

    def _run_order(self, job: Job, adb: AdbTransport, journal: Journal, order: Order,
                   manufacturer: str, names: dict[str, str], runner: Runner) -> None:
        try:
            result = execute_order(adb, journal, order, self._options(job, manufacturer, names),
                                   runner)
        except OrderInterrupted as exc:
            self._emit("exec:disconnected", {"order": exc.order.number})
            return
        if result.stopped:
            self._emit("exec:stopped", {"order": order.number})
        clear_cache_after_repair(result, self._settings, default_cache_dir())
        self._emit("exec:done", result_view(result, names, self._lang, manufacturer))

    @_api
    def preview_plan(self, requests: dict[str, str],
                     unlocked: list[str] | None = None) -> dict[str, Any]:
        self._require_scan()
        plan = plan_order(self._adb, self._report, dict(requests), unlocked or ())
        return plan_view(plan, self._lang)

    @_api
    def execute(self, requests: dict[str, str], unlocked: list[str] | None = None) -> dict[str, Any]:
        self._require_current()
        self._require_scan()
        self._abandon_apk()
        adb, report, match, client = self._adb, self._report, self._match, self._client
        wanted, free = dict(requests), list(unlocked or ())

        def run(job: Job) -> None:
            plan = plan_order(adb, report, wanted, free)
            if not plan.plans:
                raise AppError("nothing_to_do")
            names = {p: app_name(f, p) for p, f in plan.facts.items()}
            with self._journal() as journal:
                order = start(journal, plan, client, report, match)
                self._bind_order(journal, plan.device.serial, order.id)
                self._emit("exec:order", {"order": order.number,
                                          "plan": plan_view(plan, self._lang)})
                self._run_order(job, adb, journal, order, plan.ctx.manufacturer, names, run_order)

        return {"job_id": self._jobs.start("exec", run)}

    def _order_adb(self, number: str) -> tuple[Order, AdbTransport]:
        with self._journal() as journal:
            order = journal.order_by_number(number)
        if order is None:
            raise AppError("unknown_order", number)
        if self._adb is not None and self._serial == order.device_serial:
            return order, self._adb
        ready = {e.serial for e in list_devices(self._host) if e.state == "device"}
        if order.device_serial not in ready:
            with self._journal() as journal:
                name, imei = device_identity(journal, order.device_serial)
            raise AppError("wrong_device", order.device_serial, serial=order.device_serial,
                           device=name, imei=imei)
        return order, self._session(order.device_serial)

    @_api
    def resume(self, number: str) -> dict[str, Any]:
        self._require_current()
        order, adb = self._order_adb(number)
        with self._journal() as journal:
            if not any(a.status == "pending" for a in journal.actions(order.id)):
                raise AppError("nothing_to_resume", number)
        self._abandon_apk()
        names = self._names()

        def run(job: Job) -> None:
            manufacturer = read_device_info(adb).manufacturer
            with self._journal() as journal:
                self._bind_order(journal, order.device_serial, order.id)
                self._emit("exec:order", {"order": order.number, "plan": None})
                self._run_order(job, adb, journal, journal.order(order.id), manufacturer, names,
                                resume_steps)

        return {"job_id": self._jobs.start("resume", run)}

    @_api
    def undo(self, number: str, action_id: int | None = None,
             package: str | None = None) -> dict[str, Any]:
        order, adb = self._order_adb(number)
        with self._journal() as journal:
            targeted = targeted_actions(journal, order.id, package, action_id)
        if not targeted:
            raise AppError("no_target", number)
        self._abandon_apk()
        names = self._names()

        def run(job: Job) -> None:
            manufacturer = read_device_info(adb).manufacturer
            with self._journal() as journal:
                try:
                    result = undo_order(adb, journal, order, package=package, action_id=action_id,
                                        options=self._options(job, manufacturer, names))
                except OrderInterrupted as exc:
                    self._emit("exec:disconnected", {"order": exc.order.number})
                    return
            status = result.order.status
            self._emit("undo:done", {
                "order": order.number, "status": status,
                "status_label": order_status_label(status, self._lang),
                "errors": [error_text(key, self._lang, manufacturer) for _, key in result.errors],
                "admin_not_restored": result.admin_not_restored,
            })

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
    def stop(self, job_id: str) -> dict[str, Any]:
        return {"ok": self._jobs.stop(job_id)}

    @_api
    def answer(self, job_id: str, value: str) -> dict[str, Any]:
        return {"ok": self._jobs.answer(job_id, value)}

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

        def progress(done: int, total: int | None) -> None:
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

    # --- historia ------------------------------------------------------------------------------

    @_api
    def history(self, serial: str | None = None) -> dict[str, Any]:
        with self._journal() as journal:
            serials = journal.recent_serials()
            chosen = serial or self._serial or (serials[0] if serials else None)
            return history_view(journal, chosen, serials, self._lang)

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
                pick_file: Callable[[], str | None] | None = None) -> None:
        self._pick_folder_fn = pick_folder
        self._close_fn = close
        self._pick_file_fn = pick_file

    def _shutdown(self) -> None:
        self._updates.stop()
        self._mirror.stop()
        self._watcher.stop()
        self._abandon_apk()

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
        self._shutdown()
        return True

    @_api
    def quit(self) -> dict[str, Any]:
        job = self._order_in_progress()
        if job is not None:
            self._jobs.stop(job.id)
            self._jobs.wait(QUIT_WAIT)
        self._shutdown()
        self._quitting = True
        if self._close_fn is not None:
            self._close_fn()
        return {"ok": True}
