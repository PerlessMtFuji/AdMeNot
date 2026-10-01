from demalware.engine.apk.callgraph import SINKS, AndroguardGraph, MethodRef, Sink, find_paths
from demalware.engine.apk.components import Component

BOOT = "android.intent.action.BOOT_COMPLETED"


class FakeGraph:
    def __init__(self, edges, sink_callers, refs=()):
        self.edges, self.sink_callers, self.refs = edges, sink_callers, set(refs)

    def callers(self, m):
        return self.edges.get(m, ())

    def callers_of_sink(self, s):
        return self.sink_callers.get(s.id, ())

    def references(self, cls):
        return cls in self.refs


def _origin(cls):
    return "sdk" if cls.startswith("com.ads.") else "app" if cls.startswith("com.x.") else "unknown"


RECEIVER = Component("receiver", "com.x.Boot", True, None, (BOOT,))
SHOW = MethodRef("com.x.AdShow", "show")
ON_RECEIVE = MethodRef("com.x.Boot", "onReceive")


def test_boot_receiver_reaching_start_activity_is_a_boot_path():
    graph = FakeGraph({SHOW: (ON_RECEIVE,)}, {"start_activity": (SHOW,)})
    result = find_paths(graph, (RECEIVER,), origin_of=_origin)
    boot = [p for p in result.paths if p.sink == "boot_start_activity"]
    assert len(boot) == 1
    assert boot[0].entry == "com.x.Boot" and boot[0].entry_action == BOOT
    assert boot[0].chain == ("com.x.Boot.onReceive", "com.x.AdShow.show")
    assert boot[0].origin == "app"


def test_sink_without_route_to_a_component_has_no_entry():
    graph = FakeGraph({}, {"hide_icon": (MethodRef("com.ads.Hider", "run"),)})
    (path,) = [p for p in find_paths(graph, (RECEIVER,), origin_of=_origin).paths if p.sink == "hide_icon"]
    assert path.entry is None and path.origin == "sdk"


def test_cycles_terminate():
    a, b = MethodRef("com.x.A", "a"), MethodRef("com.x.B", "b")
    graph = FakeGraph({a: (b,), b: (a,)}, {"dex_load": (a,)})
    assert find_paths(graph, (RECEIVER,), origin_of=_origin).paths


def test_node_limit_is_reported_as_undetermined_not_as_clean():
    chain = {MethodRef("com.x.C", f"m{i}"): (MethodRef("com.x.C", f"m{i + 1}"),) for i in range(50)}
    graph = FakeGraph(chain, {"dex_load": (MethodRef("com.x.C", "m0"),)})
    result = find_paths(graph, (RECEIVER,), origin_of=_origin, max_nodes=10)
    assert "limit" in result.undetermined


def test_reflection_is_reported_as_undetermined():
    graph = FakeGraph({}, {}, refs={"java.lang.reflect.Method"})
    assert "reflection" in find_paths(graph, (RECEIVER,), origin_of=_origin).undetermined


class ByClassGraph(FakeGraph):
    """Jak FakeGraph, ale wywołujący sink zależą od klasy wariantu, nie od id."""

    def callers_of_sink(self, s):
        return self.sink_callers.get(s.cls, ())


def test_sink_variants_share_an_id():
    assert Sink("overlay_add", "android.view.ViewManager", "addView") in SINKS
    assert Sink("start_activity", "android.app.Activity", "startActivity") in SINKS
    assert Sink("start_activity", "android.content.ContextWrapper", "startActivity") in SINKS


def test_one_caller_reached_through_two_sink_variants_is_one_path():
    overlay = MethodRef("com.ads.Popup", "show")
    graph = ByClassGraph({}, {"android.view.WindowManager": (overlay,), "android.view.ViewManager": (overlay, overlay)})
    paths = [p for p in find_paths(graph, (RECEIVER,), origin_of=_origin).paths if p.sink == "overlay_add"]
    assert len(paths) == 1 and paths[0].origin == "sdk"


def test_activity_start_activity_variant_counts_for_boot_path():
    graph = ByClassGraph({SHOW: (ON_RECEIVE,)}, {"android.app.Activity": (SHOW,)})
    sinks = {p.sink for p in find_paths(graph, (RECEIVER,), origin_of=_origin).paths}
    assert sinks == {"start_activity", "boot_start_activity"}


def test_node_budget_is_reported_as_undetermined():
    root = MethodRef("com.x.W", "root")
    wide = {root: tuple(MethodRef("com.x.W", f"w{i}") for i in range(30))}
    graph = FakeGraph(wide, {"dex_load": (root,)})
    result = find_paths(graph, (RECEIVER,), origin_of=_origin, max_depth=100, max_nodes=5)
    assert "limit" in result.undetermined
    assert all(p.entry is None for p in result.paths)


def test_found_path_with_unexplored_deep_branch_is_not_undetermined():
    deep = {SHOW: (ON_RECEIVE, MethodRef("com.x.D", "d0"))}
    deep.update({MethodRef("com.x.D", f"d{i}"): (MethodRef("com.x.D", f"d{i + 1}"),) for i in range(20)})
    graph = FakeGraph(deep, {"hide_icon": (SHOW,)})
    result = find_paths(graph, (RECEIVER,), origin_of=_origin)
    assert [p.entry for p in result.paths] == ["com.x.Boot"]
    assert result.undetermined == []


# --- adapter na sztucznym `dx` (kształt jak androguard 4.1.4: xref = (ClassAnalysis, MethodAnalysis, offset))


def _desc(cls):
    return "L" + cls.replace(".", "/") + ";"


class _Method:
    def __init__(self, cls, name, external):
        self.class_name, self.name, self._external, self.xref_from = _desc(cls), name, external, []

    def is_external(self):
        return self._external

    def get_xref_from(self):
        return [(None, caller, 0) for caller in self.xref_from]


class _Class:
    def __init__(self, cls, extends, implements=()):
        self.name, self.extends, self.implements = _desc(cls), _desc(extends), [_desc(i) for i in implements]

    def is_external(self):
        return False


class _Dx:
    def __init__(self, methods, classes, external_classes=()):
        self.methods, self.classes, self.external = methods, classes, {_desc(c) for c in external_classes}

    def get_methods(self):
        return iter(self.methods)

    def get_classes(self):
        return iter(self.classes)

    def get_class_analysis(self, desc):
        known = {c.name for c in self.classes} | self.external
        return object() if desc in known else None


def _call(callee, caller):
    callee.xref_from.append(caller)


def test_adapter_finds_start_activity_called_on_app_activity_subclass():
    # `this.startActivity(i)` w aktywności aplikacji: androguard tworzy metodę zewnętrzną na klasie aplikacji.
    on_create = _Method("com.x.Main", "onCreate", False)
    stub = _Method("com.x.Main", "startActivity", True)
    _call(stub, on_create)
    dx = _Dx([on_create, stub], [_Class("com.x.Main", "androidx.appcompat.app.AppCompatActivity"),
                                 _Class("androidx.appcompat.app.AppCompatActivity", "android.app.Activity")])
    graph = AndroguardGraph(dx)
    sink = Sink("start_activity", "android.content.Context", "startActivity")
    assert list(graph.callers_of_sink(sink)) == [MethodRef("com.x.Main", "onCreate")]


def test_adapter_does_not_treat_an_app_override_as_the_sink():
    override = _Method("com.x.Base", "startActivity", False)
    user = _Method("com.x.Util", "go", False)
    _call(override, user)
    dx = _Dx([override, user], [_Class("com.x.Base", "android.app.Activity")])
    sink = Sink("start_activity", "android.content.Context", "startActivity")
    assert list(AndroguardGraph(dx).callers_of_sink(sink)) == []


def test_adapter_reaches_component_through_inherited_entry_method():
    # Main dziedziczy onCreate z Base (klasa aplikacji); Base.onCreate wywołuje sink.
    base_on_create = _Method("com.x.Base", "onCreate", False)
    hider = _Method("android.content.pm.PackageManager", "setComponentEnabledSetting", True)
    _call(hider, base_on_create)
    dx = _Dx([base_on_create, hider], [_Class("com.x.Base", "android.app.Activity"), _Class("com.x.Main", "com.x.Base")])
    main = Component("activity", "com.x.Main", True, None, ("android.intent.action.MAIN",))
    (path,) = find_paths(AndroguardGraph(dx), (main,), origin_of=_origin).paths
    assert path.sink == "hide_icon" and path.entry == "com.x.Main"
    assert path.chain == ("com.x.Main.onCreate", "com.x.Base.onCreate")


def test_adapter_reflection_reference():
    dx = _Dx([], [], external_classes=("java.lang.reflect.Method",))
    assert AndroguardGraph(dx).references("java.lang.reflect.Method")
    assert not AndroguardGraph(_Dx([], [])).references("java.lang.reflect.Method")
