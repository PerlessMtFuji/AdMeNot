"""Możliwe ścieżki w kodzie od komponentu (punktu wejścia) do wrażliwego wywołania.

Ocena 2026-10-01 §7.1: ścieżka statyczna to możliwość, nie dowód wykonania. Refleksja i limity
dają „nie ustalono”, nigdy „brak ścieżki = bezpiecznie”.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from admenot.engine.apk.components import Component

BOOT = "android.intent.action.BOOT_COMPLETED"
REFLECTION = "java.lang.reflect.Method"


@dataclass(frozen=True)
class MethodRef:
    cls: str
    name: str

    def __str__(self) -> str:
        return f"{self.cls}.{self.name}"


@dataclass(frozen=True)
class Sink:
    id: str
    cls: str
    name: str


# Kilka wariantów może mieć ten sam id: R8 przepina wywołanie na klasę deklarującą metodę
# (WindowManager.addView → ViewManager.addView), a wywołanie na podklasie zostaje przy niej
# (Activity.startActivity). Warianty dopisane po przebiegu na korpusie lokalnym (Task 11).
SINKS = (
    Sink("hide_icon", "android.content.pm.PackageManager", "setComponentEnabledSetting"),
    Sink("dex_load", "dalvik.system.DexClassLoader", "<init>"),
    Sink("dex_load_mem", "dalvik.system.InMemoryDexClassLoader", "<init>"),
    Sink("overlay_add", "android.view.WindowManager", "addView"),
    Sink("overlay_add", "android.view.ViewManager", "addView"),
    Sink("a11y_gesture", "android.accessibilityservice.AccessibilityService", "dispatchGesture"),
    Sink("a11y_read", "android.accessibilityservice.AccessibilityService", "getRootInActiveWindow"),
    Sink("start_activity", "android.content.Context", "startActivity"),
    Sink("start_activity", "android.content.ContextWrapper", "startActivity"),
    Sink("start_activity", "android.app.Activity", "startActivity"),
)
ENTRY_METHODS = {
    "receiver": ("onReceive",),
    "service": ("onCreate", "onStartCommand", "onAccessibilityEvent", "onServiceConnected"),
    "activity": ("onCreate", "onResume"),
    "activity-alias": (),
    "provider": ("onCreate",),
}


class MethodGraph(Protocol):
    def callers(self, m: MethodRef) -> Iterable[MethodRef]: ...
    def callers_of_sink(self, s: Sink) -> Iterable[MethodRef]: ...
    def references(self, cls: str) -> bool: ...


@dataclass(frozen=True)
class CodePath:
    sink: str
    entry: str | None  # klasa komponentu; None = w limicie nie znaleziono drogi z komponentu
    entry_action: str | None
    chain: tuple[str, ...]  # od punktu wejścia do metody wywołującej sink
    origin: str  # app | sdk | library | unknown — pochodzenie metody wywołującej sink


@dataclass
class PathSearch:
    paths: list[CodePath] = field(default_factory=list)
    undetermined: list[str] = field(default_factory=list)

    def _mark(self, reason: str) -> None:
        if reason not in self.undetermined:
            self.undetermined.append(reason)


def _entries(components: Iterable[Component]) -> dict[MethodRef, Component]:
    return {MethodRef(c.name, m): c for c in components for m in ENTRY_METHODS.get(c.kind, ())}


def _callers_by_sink(graph: MethodGraph, sinks: Iterable[Sink]) -> dict[str, list[MethodRef]]:
    # Warianty jednego sinka: metoda wywołująca dwa warianty (albo dwa przeciążenia) = jedna ścieżka.
    grouped: dict[str, dict[MethodRef, None]] = {}
    for sink in sinks:
        grouped.setdefault(sink.id, {}).update(dict.fromkeys(graph.callers_of_sink(sink)))
    return {sid: list(callers) for sid, callers in grouped.items()}


def find_paths(graph: MethodGraph, components: Iterable[Component],
               sinks: Iterable[Sink] = SINKS, *, origin_of: Callable[[str], str],
               max_depth: int = 8, max_nodes: int = 20_000) -> PathSearch:
    entries = _entries(components)
    result = PathSearch()
    visited_total = 0
    for sink_id, callers in _callers_by_sink(graph, sinks).items():
        for caller in callers:
            # BFS wstecz: od metody wywołującej sink do metod-punktów wejścia komponentów.
            queue: deque[tuple[MethodRef, tuple[MethodRef, ...]]] = deque([(caller, (caller,))])
            seen = {caller}
            reached: list[tuple[Component, tuple[MethodRef, ...]]] = []
            truncated = False
            while queue:
                method, chain = queue.popleft()
                if method in entries:
                    reached.append((entries[method], chain))
                    continue
                visited_total += 1
                if visited_total > max_nodes:
                    result._mark("limit")
                    truncated = True
                    break
                ups = [up for up in graph.callers(method) if up not in seen]
                if len(chain) >= max_depth:
                    truncated = truncated or bool(ups)
                    continue
                for up in ups:
                    seen.add(up)
                    queue.append((up, (up, *chain)))
            origin = origin_of(caller.cls)
            if truncated:  # odcięta gałąź mogła prowadzić do innego komponentu = nie ustalono
                result._mark("limit")
            if not reached:
                result.paths.append(CodePath(sink_id, None, None, (str(caller),), origin))
            for comp, chain in reached:
                text = tuple(str(m) for m in chain)
                action = next((a for a in comp.actions if a == BOOT), comp.actions[0] if comp.actions else None)
                result.paths.append(CodePath(sink_id, comp.name, action, text, origin))
                if sink_id == "start_activity" and comp.kind == "receiver" and BOOT in comp.actions:
                    result.paths.append(CodePath("boot_start_activity", comp.name, BOOT, text, origin))
    if graph.references(REFLECTION):
        result._mark("reflection")
    return result


# Androguard nie zna hierarchii klas spoza APK; tu tylko nadtypy prowadzące do klas sinków.
FRAMEWORK_SUPERTYPES = {
    "android.app.Activity": ("android.view.ContextThemeWrapper",),
    "android.view.ContextThemeWrapper": ("android.content.ContextWrapper",),
    "android.content.ContextWrapper": ("android.content.Context",),
    "android.app.Application": ("android.content.ContextWrapper",),
    "android.app.Service": ("android.content.ContextWrapper",),
    "android.app.IntentService": ("android.app.Service",),
    "android.app.job.JobService": ("android.app.Service",),
    "android.service.notification.NotificationListenerService": ("android.app.Service",),
    "android.inputmethodservice.AbstractInputMethodService": ("android.app.Service",),
    "android.inputmethodservice.InputMethodService": ("android.inputmethodservice.AbstractInputMethodService",),
    "android.accessibilityservice.AccessibilityService": ("android.app.Service",),
    "android.view.WindowManager": ("android.view.ViewManager",),
}


def _dotted(descriptor: str) -> str:
    if descriptor.startswith("L") and descriptor.endswith(";"):
        return descriptor[1:-1].replace("/", ".")
    return descriptor


class AndroguardGraph:
    """Adapter `MethodGraph` na `androguard.core.analysis.analysis.Analysis` (`dx`).

    Indeks budowany raz: `find_methods` (regex po wszystkich metodach) dla każdego węzła BFS
    trwa ~20 ms na dużej aplikacji. Wywołanie metody odziedziczonej przez podklasę androguard
    zapisuje jako osobną metodę zewnętrzną na podklasie — stąd aliasy `Podklasa.m` → `Baza.m`.
    """

    def __init__(self, dx) -> None:
        self.dx = dx
        self._methods: dict[MethodRef, list] = {}  # MethodRef -> [MethodAnalysis]
        for ma in dx.get_methods():
            self._methods.setdefault(MethodRef(_dotted(ma.class_name), ma.name), []).append(ma)
        self._by_name: dict[str, list[MethodRef]] = {}
        for ref in self._methods:
            self._by_name.setdefault(ref.name, []).append(ref)
        self._supers: dict[str, tuple[str, ...]] = {}
        self._children: dict[str, list[str]] = {}
        for ca in dx.get_classes():
            if ca.is_external():
                continue
            name = _dotted(ca.name)
            sups = tuple(_dotted(s) for s in (ca.extends, *ca.implements) if s)
            self._supers[name] = sups
            for s in sups:
                self._children.setdefault(s, []).append(name)
        self._ancestors: dict[str, frozenset[str]] = {}

    def _defines(self, ref: MethodRef) -> bool:
        return any(not ma.is_external() for ma in self._methods.get(ref, ()))

    def _xref_callers(self, ref: MethodRef) -> Iterator[MethodRef]:
        for ma in self._methods.get(ref, ()):
            for _, caller, _ in ma.get_xref_from():
                yield MethodRef(_dotted(caller.class_name), caller.name)

    def _ancestors_of(self, cls: str) -> frozenset[str]:
        if cls not in self._ancestors:
            found: set[str] = set()
            todo = [cls]
            while todo:
                cur = todo.pop()
                for s in self._supers.get(cur) or FRAMEWORK_SUPERTYPES.get(cur, ()):
                    if s not in found:
                        found.add(s)
                        todo.append(s)
            self._ancestors[cls] = frozenset(found)
        return self._ancestors[cls]

    def callers(self, m: MethodRef) -> Iterator[MethodRef]:
        seen: set[MethodRef] = set()
        for ref in self._xref_callers(m):
            if ref not in seen:
                seen.add(ref)
                yield ref
        # Podklasy bez własnej wersji metody: wywołanie `Podklasa.m` (i wejście komponentu
        # dziedziczącego np. onCreate z klasy bazowej aplikacji) trafia w `m`.
        todo = list(self._children.get(m.cls, ()))
        while todo:
            sub = todo.pop()
            alias = MethodRef(sub, m.name)
            if self._defines(alias) or alias in seen:
                continue
            seen.add(alias)
            yield alias
            todo.extend(self._children.get(sub, ()))

    def callers_of_sink(self, s: Sink) -> Iterator[MethodRef]:
        seen: set[MethodRef] = set()
        for ref in self._by_name.get(s.name, ()):
            if not (ref.cls == s.cls or s.cls in self._ancestors_of(ref.cls)):
                continue
            if ref.cls != s.cls and self._defines(ref):
                continue  # własne nadpisanie w aplikacji: jego wywołanie super złapie sink bezpośrednio
            for caller in self._xref_callers(ref):
                if caller not in seen:
                    seen.add(caller)
                    yield caller

    def references(self, cls: str) -> bool:
        return self.dx.get_class_analysis("L" + cls.replace(".", "/") + ";") is not None
