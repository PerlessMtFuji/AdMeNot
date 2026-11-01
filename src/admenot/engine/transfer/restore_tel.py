"""Silnik wgrywania telefonii: kontakty, SMS, MMS i połączenia na nowy telefon (spec Etapu 3 §4–§6).

Dla każdej kategorii (w kolejności `ORDER`) próbuje dróg z `CHAIN` po kolei, podając każdej tylko
rekordy jeszcze niezapisane:
* `app_process` — pomocnik `.dex` jako shell (dla SMS/MMS najpierw appop `WRITE_SMS` = `allow`);
* `companion` — aplikacja pomocnicza (`am instrument`); dla SMS/MMS jako tymczasowa domyślna aplikacja
  SMS, ale rola jest brana dopiero po pozostałych kategoriach (może wymagać stuknięcia, §6.2);
* `file` — pliki do ręcznego importu w `Download/` (`telfile`).

Gwarancje:
* kopia bezpieczeństwa każdej wybranej kategorii nowego telefonu przed pierwszym zapisem, raz na stan
  (meta `safety_done`); odmowa odczytu nie wstrzymuje zapisu (tylko dopisujemy);
* stan rekordu (`tel`) zapisywany po każdej paczce (najwyżej `BATCH` rekordów, jedno uruchomienie
  pomocnika) — wznowienie nie zapisze go drugi raz;
* rozłączenie nie zużywa prób: jedno `wait_device()`, ponowny odczyt kluczy kategorii z telefonu
  (wiersze zapisane przed urwaniem nie mają linii `OK`) i dopiero reszta wraca do kolejki;
* `ERR` pomocnika: ponowienie, a po `MAX_ATTEMPTS` próbach rekord idzie następną drogą (per
  wiadomość, spec §5.3); `DENIED`: cała reszta kategorii następną drogą; `error` dopiero, gdy nie zapisze
  go żadna droga (także plik);
* telefon nie daje się odczytać po urwanej paczce: jej rekordy od razu do pliku (bez duplikatów);
* po zapisie SMS/MMS sprawdzenie, że wiadomości mają wątki (inaczej `visible_warning`);
* sprzątanie (`phonesetup.cleanup`) zawsze na końcu, także po zatrzymaniu i wyjątku.

Odczyty (kopia bezpieczeństwa, klucze po rozłączeniu, widoczność) idą przez `read_adb` (strażnik
odczytu), zapisy przez `adb` (`guard.TelephonyWriteAdb`). Do logu trafiają wyłącznie liczby.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from admenot.engine.paths import device_dir_name

from ..adb.transport import AdbError, AdbTransport
from ..device.info import DeviceInfo
from . import telephony as tel
from .backup import MAX_ATTEMPTS, MAX_DISCONNECTS
from .helper import AppProcessWriter, CompanionWriter, HelperBroken, Writer
from .mms import OWN_TOKEN, _ms
from .phonesetup import (
    CleanupResult,
    cleanup,
    install_companion,
    mark_helper_dir,
    set_appop_allow,
    take_sms_role,
)
from .pusher import Pusher
from .restore import RestoreError
from .restore_state import RestoreState
from .store import CopyDir
from .telephony import Stopped, export_telephony
from .telfile import ManualFileError, ManualStep, write_manual_files
from .telplan import TelPlan, call_key, mms_key, phone_has, record_id, sms_key

log = logging.getLogger(__name__)

AP, CO, FILE = "app_process", "companion", "file"
# Wynik spike'u (Task 1): `app_process` zapisał każdą kategorię na OPPO; łańcuch bez zmian.
CHAIN: dict[str, tuple[str, ...]] = {"contacts": (AP, CO, FILE), "sms": (AP, CO, FILE),
                                     "mms": (AP, CO, FILE), "calls": (AP, CO, FILE)}
ORDER = ("contacts", "sms", "mms", "calls")
BATCH = 500  # rekordów na jedno uruchomienie pomocnika
ROLE_KINDS = frozenset({"sms", "mms"})  # droga `companion` wymaga roli SMS
CONVERSATIONS_URI = "content://mms-sms/conversations?simple=true"
_RANK = {AP: 1, CO: 2, FILE: 3}
_FILES_BAD = ("pending", "pushing", "error", "denied")

Path_ = Literal["app_process", "companion", "file", "none"]
OnTap = Callable[[str | None], None]
WriterFactory = Callable[[str, AdbTransport, Pusher, tuple[str, str] | None], Writer]
Rec = tuple[str, Any]  # (id rekordu, rekord z `telrecords`)


@dataclass(frozen=True)
class TelProgress:
    kind: str
    done: int
    total: int
    path: str


@dataclass(frozen=True)
class TelKindResult:
    written: int
    existed: int
    skipped_synced: int
    skipped_messenger: int
    failed: int
    manual: int
    path: Path_
    visible_warning: bool


@dataclass(frozen=True)
class TelResult:
    kinds: dict[str, TelKindResult]
    safety: dict[str, bool]  # kategoria -> czy kopia bezpieczeństwa nowego telefonu się udała
    manual: list[ManualStep]
    cleanup: CleanupResult
    synced_accounts: dict[str, int]  # konto -> kontakty pominięte (przyjdą z synchronizacji); tylko do UI
    seconds: int
    stopped: bool = False  # przerwane na żądanie; reszta zostaje do wznowienia

    @property
    def status(self) -> Literal["complete", "incomplete"]:
        bad = self.stopped or not self.cleanup.ok or bool(self.manual)
        bad = bad or any(k.failed or k.manual for k in self.kinds.values())
        return "incomplete" if bad else "complete"


def default_writers(key: str, adb: AdbTransport, pusher: Pusher, account: tuple[str, str] | None) -> Writer:
    if key == AP:
        return AppProcessWriter(adb, pusher, account)
    if key == CO:
        return CompanionWriter(adb, pusher, account)
    raise ValueError(f"unknown writer {key!r}")


def run_tel_restore(adb: AdbTransport, read_adb: AdbTransport, pusher: Pusher, device: DeviceInfo,
                    copy: CopyDir, plan: TelPlan, kinds: frozenset[str], state: RestoreState, *,
                    on_progress: Callable[[TelProgress], None], should_stop: Callable[[], bool],
                    wait_device: Callable[[], None], on_tap: OnTap, skip_tap: Callable[[], bool],
                    writers: WriterFactory = default_writers) -> TelResult:
    """Zapisuje wybrane kategorie planu na telefon `device` (`kinds` ⊆ ORDER; `sms` obejmuje MMS).

    `adb` — `phonesetup.telephony_adb(...)` dla tego `state`; `read_adb` — `guard.ReadOnlyAdb`.
    `RestoreError` (np. za dużo rozłączeń) przechodzi wyżej po sprzątaniu; zatrzymanie daje
    `TelResult.stopped`, a stan zostaje do wznowienia."""
    return _TelRestore(adb, read_adb, pusher, device, copy, plan, kinds, state, on_progress, should_stop,
                       wait_device, on_tap, skip_tap, writers).run()


class _Stop(Exception):
    """Przerwanie na żądanie (wewnętrzne)."""


def _noop() -> None:
    return None


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _missing_part(rec: Any) -> bool:
    """MMS z częścią, której pliku nie ma już w kopii (pomocnik dostaje części jako pliki)."""
    return any(p.file is not None and not p.file.is_file() for p in rec.parts)


def _mark(state: RestoreState, status: str) -> None:
    state.set_meta("status", status)
    state.set_meta("updated", datetime.now(UTC).isoformat(timespec="seconds"))


@dataclass
class _Kind:
    total: int = 0
    done: int = 0
    written: list[Any] = field(default_factory=list)  # rekordy zapisane w tym przebiegu (widoczność)


class _TelRestore:
    def __init__(self, adb: AdbTransport, read_adb: AdbTransport, pusher: Pusher, device: DeviceInfo,
                 copy: CopyDir, plan: TelPlan, kinds: frozenset[str], state: RestoreState,
                 on_progress: Callable[[TelProgress], None], should_stop: Callable[[], bool],
                 wait_device: Callable[[], None], on_tap: OnTap, skip_tap: Callable[[], bool],
                 writers: WriterFactory) -> None:
        self.adb, self.read_adb, self.pusher, self.device, self.copy = adb, read_adb, pusher, device, copy
        self.plan, self.state = plan, state
        self.on_progress, self.should_stop, self.wait_device = on_progress, should_stop, wait_device
        self.on_tap, self.skip_tap, self.writers = on_tap, skip_tap, writers
        want = set(kinds) | ({"mms"} if "sms" in kinds else set())
        src = plan.sources
        present = {"contacts": src.contacts is not None and plan.contacts is not None,
                   "sms": src.sms is not None, "mms": src.mms is not None, "calls": src.calls is not None}
        self.kinds = [k for k in ORDER if k in want and present[k]]
        self.records = {k: self._records(k) for k in self.kinds}
        self.stats = {k: _Kind() for k in self.kinds}
        self.disconnects = 0
        self.attempts: dict[tuple[str, str, str], int] = {}  # (kategoria, droga, id) -> próby
        self.codes: dict[tuple[str, str], str] = {}  # (kategoria, id) -> ostatni kod błędu pomocnika
        self.deferred: list[tuple[str, list[Rec], tuple[str, ...]]] = []
        self.manual: dict[str, list[Rec]] = {}
        self.cache: dict[str, Writer] = {}
        self.appop: bool | None = None
        self.companion: str | None = None
        self.role: str | None = None
        self.safety: dict[str, bool] = dict.fromkeys(self.kinds, False)
        self.visible: dict[str, bool] = {}

    # ---- rekordy --------------------------------------------------------------------------
    def _records(self, kind: str) -> list[Rec]:
        p = self.plan
        if kind == "contacts":
            assert p.contacts is not None
            pairs = [(record_id(("contact", c.source_id)), c) for c in p.contacts.write]
        elif kind == "sms":
            pairs = [(record_id(sms_key(r)), r) for r in p.sms]
        elif kind == "mms":
            pairs = [(record_id(mms_key(r)), r) for r in p.mms]
        else:
            pairs = [(record_id(call_key(r)), r) for r in p.calls]
        unique: dict[str, Any] = {}
        for rid, rec in pairs:  # bez powtórzonych kluczy, kolejność z kopii
            unique.setdefault(rid, rec)
        return list(unique.items())

    # ---- przebieg -------------------------------------------------------------------------
    def run(self) -> TelResult:
        t0 = time.monotonic()
        st, serial = self.state, self.device.serial
        if st.get_meta("serial", serial) != serial:
            raise RestoreError("wrong_device")
        st.set_meta("serial", serial)  # przed pierwszą zmianą telefonu (widok kopii, Banner sprzątania)
        _mark(st, "running")
        todo: dict[str, list[Rec]] = {}
        for k in self.kinds:
            known = st.tel_status(k)
            todo[k] = [r for r in self.records[k] if known.get(r[0]) not in ("done", "manual")]
            self.stats[k].total = len(todo[k])
        # Banner wznowienia (`read_restores`): do końca przebiegu wszystko z kolejki liczy się jako
        # niezrobione, także po zamknięciu programu w trakcie
        st.set_meta("tel_left", sum(len(v) for v in todo.values()))
        stopped = False
        try:
            try:
                self._safety()
                self._write_all(todo)
                self._check_visible()
            except _Stop:
                stopped = True
            finally:
                clean = self._cleanup()
        except RestoreError as exc:
            _mark(st, exc.key)
            raise
        except BaseException:
            _mark(st, "incomplete")
            raise
        result = self._result(clean, stopped, t0)
        _mark(st, "stopped" if stopped else self._final_status(result))
        return result

    def _final_status(self, result: TelResult) -> str:
        """Stan całego wgrywania (pliki z Etapu 2 + telefonia) dla widoku kopii."""
        files_bad = any(r.status in _FILES_BAD for r in self.state.all_files().values())
        return "incomplete" if files_bad else result.status

    def _cleanup(self) -> CleanupResult:
        try:
            return cleanup(self.adb, self.state, self.on_tap, self.should_stop)
        except AdbError:
            return CleanupResult(False, False, False, False)

    # ---- telefon --------------------------------------------------------------------------
    def _online(self) -> bool:
        try:
            return self.adb.run(["get-state"]).strip() == "device"
        except AdbError:
            return False

    def _disconnected(self) -> None:
        self.disconnects += 1
        if self.disconnects > MAX_DISCONNECTS:
            raise RestoreError("too_many_disconnects")
        self.wait_device()

    def _connection(self, exc: AdbError) -> bool:
        return exc.kind in tel._CONNECTION_KINDS or not self._online()

    def _retry(self, fn: Callable[[], Any]) -> Any:
        """Krok na telefonie: rozłączenie -> czekanie na telefon i ponowienie; inny błąd wyżej."""
        while True:
            if self.should_stop():
                raise _Stop()
            try:
                return fn()
            except Stopped:
                raise _Stop() from None
            except AdbError as exc:
                if not self._connection(exc):
                    raise
                self._disconnected()

    # ---- kopia bezpieczeństwa -------------------------------------------------------------
    def _safety(self) -> None:
        done: dict[str, bool] = dict(self.state.get_meta("safety_done") or {})
        need = [k for k in self.kinds if k not in done]
        if need:
            out = self.copy.path / "restore" / f"{device_dir_name(self.device.serial)}-safety"
            res = self._retry(lambda: export_telephony(
                self.read_adb, out, contacts="contacts" in need, sms="sms" in need, calls="calls" in need,
                mms="mms" in need, shell_v2=self.device.sdk >= 24, should_stop=self.should_stop))
            for k in need:
                done[k] = k in res and res[k].status == "ok"
            self.state.set_meta("safety_done", done)
        self.safety = {k: bool(done.get(k)) for k in self.kinds}

    # ---- kategorie i drogi ----------------------------------------------------------------
    def _write_all(self, todo: dict[str, list[Rec]]) -> None:
        for kind in self.kinds:
            if todo[kind]:
                self._progress(kind, CHAIN[kind][0])
                self._kind(kind, todo[kind], CHAIN[kind], defer=True)
        # pliki kategorii bez roli (kontakty + okno importu, połączenia) przed czekaniem na stuknięcie
        self._write_files(set(self.manual) - ROLE_KINDS)
        for kind, recs, chain in self.deferred:  # rola SMS dopiero po pozostałych kategoriach (§6.2)
            self._kind(kind, recs, chain, defer=False)
        self._write_files(set(self.manual))

    def _kind(self, kind: str, records: list[Rec], chain: tuple[str, ...], *, defer: bool) -> None:
        """Rekordy przechodzą drogi po kolei: następna dostaje te, których poprzednia nie zapisała
        (odmowa, pomocnik niedostępny albo `ERR` po `MAX_ATTEMPTS` próbach — spec §5.3, R15)."""
        remaining = records
        for i, route in enumerate(chain):
            if not remaining:
                return
            if route == FILE:
                self.manual.setdefault(kind, []).extend(remaining)
                return
            if route == CO and kind in ROLE_KINDS and defer:
                self.deferred.append((kind, remaining, chain[i:]))
                return
            if self._prepare(route, kind):
                remaining = self._route(kind, route, remaining)
        for code, rids in self._by_code(kind, remaining, "no_route").items():  # łańcuch bez drogi „plik”
            self.state.tel_set(kind, rids, "error", chain[-1], code)
            self.stats[kind].done += len(rids)

    def _by_code(self, kind: str, recs: list[Rec], default: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for rid, _ in recs:
            out.setdefault(self.codes.get((kind, rid), default)[:40], []).append(rid)
        return out

    def _prepare(self, route: str, kind: str) -> bool:
        """Zmiany telefonu potrzebne drodze (raz na przebieg). `False` = droga niedostępna."""
        try:
            if route == AP:
                if kind in ROLE_KINDS and self.appop is None:
                    self._retry(lambda: set_appop_allow(self.adb, self.state))
                    self.appop = True
                return kind not in ROLE_KINDS or bool(self.appop)
            if self.companion is None:
                try:
                    self.companion = self._retry(lambda: install_companion(self.adb, self.state))
                except HelperBroken as exc:
                    log.warning("companion app unusable: %s", exc)
                    self.companion = "blocked"
            if self.companion != "ok":
                return False
            if kind in ROLE_KINDS:
                if self.role is None:
                    self.role = self._retry(lambda: take_sms_role(self.adb, self.state, self.on_tap,
                                                                  self.should_stop, self.skip_tap))
                    if self.should_stop():
                        raise _Stop()
                return self.role == "ok"
            return True
        except AdbError as exc:
            log.warning("telephony route %s unavailable for %s: %s", route, kind, exc.kind)
            if route == AP and kind in ROLE_KINDS:
                self.appop = False
            elif route == CO and self.companion is None:
                self.companion = "blocked"
            elif route == CO and kind in ROLE_KINDS:
                self.role = "skipped"
            return False

    def _writer(self, route: str) -> Writer:
        if route not in self.cache:
            self.cache[route] = self.writers(route, self.adb, self.pusher, self.plan.local_account)
        return self.cache[route]

    def _route(self, kind: str, route: str, records: list[Rec]) -> list[Rec]:
        """Zapis drogą `route` paczkami; zwraca rekordy dla następnej drogi (odmowa albo pomocnik
        niedostępny)."""
        writer = self._writer(route)
        pending = list(records)
        onward: list[Rec] = []
        while pending:
            if self.should_stop():
                raise _Stop()
            chunk, pending = pending[:BATCH], pending[BATCH:]
            retry, passed, abandon = self._chunk(kind, route, writer, chunk)
            self._progress(kind, route)
            onward += passed
            if abandon:  # odmowa albo pomocnik niedostępny: cała reszta idzie dalej
                return onward + retry + pending
            pending = retry + pending
        return onward

    def _chunk(self, kind: str, route: str, writer: Writer, chunk: list[Rec]
               ) -> tuple[list[Rec], list[Rec], bool]:
        """Jedna paczka: (do ponowienia tą drogą, dla następnej drogi, czy porzucić tę drogę)."""
        broken = [r for r in chunk if kind == "mms" and _missing_part(r[1])]
        if broken:  # plik załącznika zniknął z kopii: żadna droga z pomocnikiem go nie zapisze
            self.codes.update({(kind, rid): "missing_part" for rid, _ in broken})
            chunk = [r for r in chunk if r not in broken]
            if not chunk:
                return [], broken, False
        if route == AP:
            mark_helper_dir(self.state)
        try:
            out = writer.write(kind, chunk, _noop)
        except HelperBroken as exc:
            if self._online():
                log.warning("helper unusable for %s via %s: %s", kind, route, exc)
                return [], broken + chunk, True
            self._disconnected()
            return self._drop_present(kind, route, chunk), broken, False
        except AdbError as exc:
            if self._connection(exc):
                self._disconnected()
                return self._drop_present(kind, route, chunk), broken, False
            log.warning("helper failed for %s via %s: %s", kind, route, exc.kind)
            rest = self._drop_present(kind, route, chunk)
            retry, exhausted = self._failed(kind, route, rest, dict.fromkeys((rid for rid, _ in rest),
                                                                             "helper_failed"))
            return retry, broken + exhausted, False
        ok = [r for r in chunk if r[0] in out.ok]
        self._done(kind, route, ok)
        log.info("telephony %s via %s: %d ok, %d failed, denied=%s", kind, route, len(ok), len(out.failed),
                 out.denied)
        if out.denied:
            return [], broken + [r for r in chunk if r[0] not in out.ok], True
        bad = [r for r in chunk if r[0] in out.failed]
        missing = [r for r in chunk if r[0] not in out.ok and r[0] not in out.failed]
        if missing:
            missing = self._drop_present(kind, route, missing)
        codes = {**dict.fromkeys((rid for rid, _ in missing), "no_result"), **out.failed}
        retry, exhausted = self._failed(kind, route, bad + missing, codes)
        return retry, broken + exhausted, False

    def _drop_present(self, kind: str, route: str, recs: list[Rec]) -> list[Rec]:
        """Po urwanym zapisie: rekordy, które już są na telefonie, liczą się jako zapisane (`done`).
        Telefon nie daje się odczytać (R17): rekordy przerwanej paczki nie wracają na telefon (mogły
        zostać zapisane bez linii `OK`), tylko od razu do pliku do ręcznego importu."""
        if not recs:
            return recs
        has = self._retry(lambda: phone_has(self.read_adb, kind))
        if has is None:
            self.manual.setdefault(kind, []).extend(recs)
            return []
        present = [r for r in recs if has(r[1])]
        self._done(kind, route, present)
        return [r for r in recs if r not in present]

    def _done(self, kind: str, route: str, recs: list[Rec]) -> None:
        if not recs:
            return
        self.state.tel_set(kind, [rid for rid, _ in recs], "done", route)
        self.stats[kind].done += len(recs)
        self.stats[kind].written += [rec for _, rec in recs]
        self._used(kind, route)

    def _failed(self, kind: str, route: str, recs: list[Rec], codes: dict[str, str]
                ) -> tuple[list[Rec], list[Rec]]:
        """Nieudana próba tą drogą: (do ponowienia, wyczerpane po `MAX_ATTEMPTS` — dla następnej drogi).
        Ostatni kod błędu zostaje zapamiętany na wypadek, gdyby żadna droga go nie zapisała."""
        retry: list[Rec] = []
        exhausted: list[Rec] = []
        for rid, rec in recs:
            self.codes[(kind, rid)] = codes.get(rid, "error")
            n = self.attempts.get((kind, route, rid), 0) + 1
            self.attempts[(kind, route, rid)] = n
            (exhausted if n >= MAX_ATTEMPTS else retry).append((rid, rec))
        return retry, exhausted

    def _used(self, kind: str, route: str) -> None:
        """Najdalsza droga, którą poszły rekordy kategorii (meta `tel_path`, także z poprzednich przebiegów)."""
        paths = dict(self.state.get_meta("tel_path") or {})
        if _RANK[route] > _RANK.get(paths.get(kind, ""), 0):
            paths[kind] = route
            self.state.set_meta("tel_path", paths)

    def _progress(self, kind: str, route: str) -> None:
        s = self.stats[kind]
        self.on_progress(TelProgress(kind, s.done, s.total, route))

    # ---- droga 3 --------------------------------------------------------------------------
    def _write_files(self, kinds: set[str]) -> None:
        recs = {k: self.manual.pop(k) for k in sorted(kinds) if self.manual.get(k)}
        if not recs:
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        records = {k: [rec for _, rec in v] for k, v in recs.items()}
        while True:
            try:
                steps = self._retry(lambda: write_manual_files(self.adb, self.pusher, records, stamp))
                break
            except ManualFileError as exc:
                if self._online():
                    log.warning("manual import files not written: %s", exc)
                    for k, v in recs.items():
                        for code, rids in self._by_code(k, v, "file_failed").items():
                            self.state.tel_set(k, rids, "error", FILE, code)
                        self.stats[k].done += len(v)
                    return
                self._disconnected()
        saved = list(self.state.get_meta("tel_manual") or [])
        saved += [asdict(s) for s in steps if asdict(s) not in saved]
        self.state.set_meta("tel_manual", saved)
        for k, v in recs.items():
            self.state.tel_set(k, [rid for rid, _ in v], "manual", FILE)
            self.stats[k].done += len(v)
            self._used(k, FILE)
            self._progress(k, FILE)

    # ---- widoczność -----------------------------------------------------------------------
    def _check_visible(self) -> None:
        for kind in ("sms", "mms"):
            recs = self.stats[kind].written if kind in self.stats else []
            if recs:
                self.visible[kind] = self._retry(lambda k=kind, r=recs: self._visible_warning(k, r))

    def _visible_warning(self, kind: str, recs: list[Any]) -> bool:
        """`True`, gdy zapisane wiadomości nie mają wątku, wątków jest mniej niż rozmówców albo nie da się
        tego sprawdzić (raport mówi wtedy „sprawdź w aplikacji Wiadomości”, nie „wgrano”)."""
        try:
            rows = tel.content_query(self.read_adb, "content://sms" if kind == "sms" else "content://mms",
                                     ["_id", "thread_id", "date"])
            threads = tel.content_query(self.read_adb, CONVERSATIONS_URI, ["_id"])
        except tel.ContentQueryError:
            return True
        dates = {r.date for r in recs}
        if kind == "sms":
            mine = [row for row in rows if _int(row.get("date")) in dates]
            people = {tel.phone_key(r.address) or r.address for r in recs}
        else:
            mine = [row for row in rows if _int(_ms(row.get("date"))) in dates]
            people = {tuple(sorted(tel.phone_key(a) or a for a, _ in r.addrs if a != OWN_TOKEN)) for r in recs}
        if not mine or any((row.get("thread_id") or "0") == "0" for row in mine):
            return True
        return len(threads) < len(people)

    # ---- wynik ----------------------------------------------------------------------------
    def _result(self, clean: CleanupResult, stopped: bool, t0: float) -> TelResult:
        paths = self.state.get_meta("tel_path") or {}
        contacts = self.plan.contacts if "contacts" in self.kinds else None
        kinds: dict[str, TelKindResult] = {}
        left = 0
        for k in self.kinds:
            known = self.state.tel_status(k)
            cnt = Counter(known.get(rid) for rid, _ in self.records[k])
            left += len(self.records[k]) - cnt["done"] - cnt["manual"] - cnt["error"]
            sel = contacts if k == "contacts" else None
            kinds[k] = TelKindResult(
                written=cnt["done"], existed=self.plan.existing.get(k, 0),
                skipped_synced=sum(sel.skipped_synced.values()) if sel else 0,
                skipped_messenger=sel.skipped_messenger if sel else 0,
                failed=cnt["error"], manual=cnt["manual"], path=paths.get(k, "none"),
                visible_warning=self.visible.get(k, False))
        self.state.set_meta("tel_left", left)
        # kroki „do zrobienia” tylko dla kategorii, które nadal mają rekordy do ręcznego importu (plik
        # zaimportowany i plan bez tych rekordów -> krok znika, a przebieg może być `complete`)
        still = {"sms" if k == "mms" else k for k, v in kinds.items() if v.manual}
        saved = self.state.get_meta("tel_manual") or []
        kept = [d for d in saved if d.get("kind") in still]
        if kept != saved:
            self.state.set_meta("tel_manual", kept)
        manual = [ManualStep(d["kind"], d["remote"]) for d in kept]
        synced = dict(contacts.skipped_synced) if contacts else {}
        return TelResult(kinds, self.safety, manual, clean, synced, round(time.monotonic() - t0), stopped)
