from __future__ import annotations

import os
import re
import threading
from pathlib import Path

import pytest
from faketransfer import FakeStoragePhone

from admenot.engine.adb.transport import AdbError, classify_error
from admenot.engine.explorer.guard import ExplorerAdb, ExplorerPusher, is_tmp_name
from admenot.engine.explorer.plan import plan_to_pc, plan_to_phone
from admenot.engine.explorer.queue import (
    HASH_BASE_TIMEOUT,
    HASH_MIN_SPEED,
    TransferQueue,
    hash_timeout,
    read_part_folders,
    read_tmp_folders,
    record_part_folder,
    record_tmp_folder,
    sweep_parts,
    sweep_recorded,
    sweep_tmp,
)
from admenot.engine.transfer.puller import PullResult

OK = {"free_bytes": lambda p: 10**15, "filesystem": lambda p: "NTFS", "writable": lambda p: True}
TMP_ON_PHONE = re.compile(r"\.admenot-[0-9a-f]{12}\.part")


def put(phone: FakeStoragePhone, remote: str, data: bytes = b"x", mtime: int | None = None) -> None:
    path = phone.local(remote)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def phone_files(phone: FakeStoragePhone, remote: str) -> dict[str, bytes]:
    base = phone.local(remote)
    return {p.relative_to(base).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


def pc_files(base: Path) -> dict[str, bytes]:
    return {p.relative_to(base).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


class Events:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []
        self.lock = threading.Lock()

    def __call__(self, name: str, payload: dict) -> None:
        with self.lock:
            self.items.append((name, payload))

    def statuses(self, tid: str) -> list[str]:
        return [p["status"] for n, p in self.items if n == "explorer:task" and p["id"] == tid]


class Clock:
    def __init__(self, step: float = 0.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


@pytest.fixture
def phone(tmp_path: Path) -> FakeStoragePhone:
    return FakeStoragePhone(tmp_path / "phone")


@pytest.fixture
def adb(phone: FakeStoragePhone) -> ExplorerAdb:
    return ExplorerAdb(phone)


@pytest.fixture
def pc(tmp_path: Path) -> Path:
    d = tmp_path / "pc"
    d.mkdir()
    return d


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path / "explorer_tmp"


@pytest.fixture
def make_queue(phone, adb, tmp_dir):
    made: list[TransferQueue] = []

    def make(*, puller=None, pusher=None, emit=None, is_connected=None, **kw) -> TransferQueue:
        kw.setdefault("retry_interval", 0.001)
        kw.setdefault("tmp_dir", tmp_dir)
        kw.setdefault("sdk", lambda: 30)
        q = TransferQueue(lambda: adb, puller or phone, pusher or phone, emit or Events(),
                          is_connected or (lambda: phone.online), **kw)
        made.append(q)
        return q

    yield make
    for q in made:
        q.shutdown()


def local_tree(base: Path, files: dict[str, bytes], mtime: int = 1_600_000_000) -> None:
    for rel, data in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        os.utime(p, (mtime, mtime))


def no_phone_tmp(phone: FakeStoragePhone) -> bool:
    return not any(is_tmp_name(p.name) for p in (phone.root / "sdcard").rglob("*"))


# ---------------------------------------------------------------------------------------------


def test_copy_to_pc_keeps_tree_and_mtime(phone, adb, pc, make_queue):
    put(phone, "/sdcard/Pics/a.jpg", b"aaaa", mtime=1_500_000_000)
    put(phone, "/sdcard/Pics/sub/b.txt", b"bb", mtime=1_400_000_000)
    put(phone, "/sdcard/Pics/.hidden", b"h", mtime=1_300_000_000)
    put(phone, "/sdcard/one.mp4", b"v" * 10, mtime=1_200_000_000)
    plan = plan_to_pc(adb, ["/sdcard/Pics", "/sdcard/one.mp4"], pc, **OK)
    q = make_queue()
    tid = q.add(plan)
    st = q.wait_for(tid, "done")
    assert pc_files(pc) == {"Pics/a.jpg": b"aaaa", "Pics/sub/b.txt": b"bb", "Pics/.hidden": b"h",
                            "one.mp4": b"v" * 10}
    assert int(os.stat(pc / "Pics" / "a.jpg").st_mtime) == 1_500_000_000
    assert int(os.stat(pc / "Pics" / "sub" / "b.txt").st_mtime) == 1_400_000_000
    assert int(os.stat(pc / "one.mp4").st_mtime) == 1_200_000_000
    assert (st.done_files, st.total_files, st.done_bytes, st.total_bytes) == (4, 4, 17, 17)
    assert st.failed == [] and st.verified == "size" and st.kind == "to_pc"
    assert st.dest == str(pc)


def test_upload_uses_tmp_then_mv(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"Up/a.jpg": b"aaa", "Up/b c'$.txt": b"bb"}, mtime=1_500_000_000)
    phone.local("/sdcard/Download").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / "Up"], "/sdcard/Download")
    q = make_queue()
    st = q.wait_for(q.add(plan), "done")
    assert phone_files(phone, "/sdcard/Download") == {"Up/a.jpg": b"aaa", "Up/b c'$.txt": b"bb"}
    assert int(os.stat(phone.local("/sdcard/Download/Up/a.jpg")).st_mtime) == 1_500_000_000
    assert all(TMP_ON_PHONE.fullmatch(p.rsplit("/", 1)[1]) for p in phone.pushed)
    mvs = [c for c in phone.commands if c.startswith("mv -n ")]
    assert len(mvs) == 2
    assert all(re.fullmatch(r"mv -n '?/sdcard/Download/Up/\.admenot-[0-9a-f]{12}\.part'? .+", c) for c in mvs)
    assert no_phone_tmp(phone)
    assert st.done_files == 2 and st.verified == "size" and st.dest == "/sdcard/Download"
    assert st.kind == "to_phone"


def test_upload_never_overwrites(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"a.jpg": b"mine"})
    phone.local("/sdcard/Up").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / "a.jpg"], "/sdcard/Up")
    assert plan.items[0].action == "copy"

    def appear(cmd: str) -> None:  # klient zapisuje plik o tej samej nazwie w trakcie wgrywania
        if cmd.startswith("mv -n ") and not phone.local("/sdcard/Up/a.jpg").exists():
            put(phone, "/sdcard/Up/a.jpg", b"theirs")

    phone.on_shell = appear
    q = make_queue()
    st = q.wait_for(q.add(plan), "done")
    assert phone_files(phone, "/sdcard/Up") == {"a.jpg": b"theirs", "a (z komputera).jpg": b"mine"}
    assert st.renamed == 1 and st.done_files == 1 and st.failed == []
    assert len([c for c in phone.commands if c.startswith("mv -n ")]) == 2


def test_same_content_skipped_by_hash(phone, adb, pc, tmp_path, make_queue):
    # telefon -> komputer
    put(phone, "/sdcard/P/a.jpg", b"same")
    put(phone, "/sdcard/P/b.jpg", b"new!")
    (pc / "P").mkdir()
    (pc / "P" / "a.jpg").write_bytes(b"same")
    (pc / "P" / "b.jpg").write_bytes(b"old!")
    plan = plan_to_pc(adb, ["/sdcard/P"], pc, **OK)
    assert sorted(i.action for i in plan.items) == ["check_hash", "check_hash"]
    q = make_queue()
    st = q.wait_for(q.add(plan), "done")
    assert pc_files(pc) == {"P/a.jpg": b"same", "P/b.jpg": b"old!", "P/b (z telefonu).jpg": b"new!"}
    assert (st.skipped, st.renamed, st.done_files, st.total_files) == (1, 1, 1, 1)
    # komputer -> telefon
    src = tmp_path / "src"
    local_tree(src, {"c.txt": b"same", "d.txt": b"mine"})
    put(phone, "/sdcard/Q/c.txt", b"same")
    put(phone, "/sdcard/Q/d.txt", b"them")
    plan = plan_to_phone(adb, [src / "c.txt", src / "d.txt"], "/sdcard/Q")
    st = q.wait_for(q.add(plan), "done")
    assert phone_files(phone, "/sdcard/Q") == {"c.txt": b"same", "d.txt": b"them", "d (z komputera).txt": b"mine"}
    assert (st.skipped, st.renamed, st.done_files) == (1, 1, 1)
    assert no_phone_tmp(phone)


def test_cable_pull_waits_and_resumes(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    files = {f"Up/f{i}.bin": bytes([i]) * (100 + i) for i in range(7)}
    local_tree(src, files)
    phone.local("/sdcard/Download").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / "Up"], "/sdcard/Download")
    phone.fail_after_push_files = 3
    events = Events()
    q = make_queue(emit=events)
    tid = q.add(plan)
    q.wait_for(tid, "waiting")
    assert not phone.online
    phone.fail_after_push_files = None
    phone.reconnect()
    st = q.wait_for(tid, "done")
    assert phone_files(phone, "/sdcard/Download") == files  # każdy plik raz, bez „(z komputera)”
    assert no_phone_tmp(phone)
    assert st.done_files == 7 and st.failed == [] and st.renamed == 0
    assert "waiting" in events.statuses(tid)
    assert read_tmp_folders("FAKE", directory=q.tmp_dir) == []


def test_other_phone_does_not_resume(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"a.bin": b"a" * 10, "b.bin": b"b" * 10, "c.bin": b"c" * 10})
    phone.local("/sdcard/Up").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / "a.bin", src / "b.bin", src / "c.bin"], "/sdcard/Up")
    phone.fail_after_push_files = 1
    present = {"serials": ["FAKE"]}
    polls = threading.Semaphore(0)

    def serials() -> list[str]:
        polls.release()
        return present["serials"]

    q = make_queue(connected_serials=serials, is_connected=lambda: True)
    tid = q.wait_for(q.add(plan), "waiting").id
    phone.fail_after_push_files = None
    present["serials"] = ["OTHER"]
    phone.reconnect()  # adb odpowiada, ale podłączony jest inny telefon
    while polls.acquire(blocking=False):
        pass
    for _ in range(20):
        assert polls.acquire(timeout=5)
    assert q.tasks()[0].status == "waiting"
    pushes = phone.push_calls
    present["serials"] = ["OTHER", "FAKE"]
    q.wait_for(tid, "done")
    assert phone.push_calls > pushes
    assert phone_files(phone, "/sdcard/Up") == {"a.bin": b"a" * 10, "b.bin": b"b" * 10, "c.bin": b"c" * 10}


class GatePusher:
    """Pusher, który przy wybranym pliku zapisuje połowę na telefon i woła `action` (pauza/anulowanie)."""

    def __init__(self, phone: FakeStoragePhone, name: str, action) -> None:
        self.phone = phone
        self.name = name
        self.action = action
        self.calls: list[str] = []
        self.fired = False

    def push(self, locals_, remote, should_stop, tick):
        self.calls.append(locals_[0].name)
        if locals_[0].name == self.name and not self.fired:
            self.fired = True
            data = locals_[0].read_bytes()
            self.phone.local(remote).write_bytes(data[: len(data) // 2])
            self.action()
            while not should_stop():
                tick()
            return PullResult(1, [], True)
        return self.phone.push(locals_, remote, should_stop, tick)


def test_pause_resume_restarts_current_file(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    files = {"a.bin": b"a" * 50, "big.bin": b"B" * 400, "c.bin": b"c" * 50}
    local_tree(src, files)
    phone.local("/sdcard/Up").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / n for n in files], "/sdcard/Up")
    holder: dict[str, str] = {}
    pusher = GatePusher(phone, "big.bin", lambda: q.pause(holder["id"]))
    q = make_queue(pusher=pusher, big_file=100)
    holder["id"] = tid = q.add(plan)
    st = q.wait_for(tid, "paused")
    assert no_phone_tmp(phone)
    assert not phone.local("/sdcard/Up/big.bin").exists()
    q.resume(tid)
    st = q.wait_for(tid, "done")
    assert phone_files(phone, "/sdcard/Up") == files
    assert pusher.calls.count("big.bin") == 2  # przerwany plik od początku
    assert st.done_files == 3 and no_phone_tmp(phone)


def test_cancel_removes_partials_both_sides(phone, adb, pc, tmp_path, make_queue, tmp_dir):
    # komputer -> telefon
    src = tmp_path / "src"
    local_tree(src, {"big.bin": b"B" * 400})
    phone.local("/sdcard/Up").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / "big.bin"], "/sdcard/Up")
    holder: dict[str, str] = {}
    pusher = GatePusher(phone, "big.bin", lambda: q.cancel(holder["id"]))
    q = make_queue(pusher=pusher)
    holder["id"] = tid = q.add(plan)
    st = q.wait_for(tid, "cancelled")
    assert phone_files(phone, "/sdcard/Up") == {}
    assert read_tmp_folders("FAKE", directory=tmp_dir) == []
    assert st.done_files == 0
    # telefon -> komputer

    class GatePuller:
        def pull(self, remotes, target, should_stop, tick):
            target.write_bytes(b"half")
            q2.cancel(holder["id2"])
            while not should_stop():
                tick()
            return PullResult(1, [], True)

    put(phone, "/sdcard/V/movie.mp4", b"M" * 100)
    plan = plan_to_pc(adb, ["/sdcard/V/movie.mp4"], pc, **OK)
    q2 = make_queue(puller=GatePuller())
    holder["id2"] = tid2 = q2.add(plan)
    q2.wait_for(tid2, "cancelled")
    assert pc_files(pc) == {}


def test_denied_folder_reports_failed_files_and_leaves_nothing(phone, adb, tmp_path, make_queue, tmp_dir):
    src = tmp_path / "src"
    local_tree(src, {"Up/a.txt": b"a", "Up/b.txt": b"b", "c.txt": b"c"})
    phone.local("/sdcard/Android/data").mkdir(parents=True)
    phone.deny_prefixes = {"/sdcard/Android/data/"}
    plan = plan_to_phone(adb, [src / "Up", src / "c.txt"], "/sdcard/Android/data")
    q = make_queue()
    st = q.wait_for(q.add(plan), "done")
    assert sorted(r for _, r in st.failed) == ["denied", "denied", "denied"]
    assert sorted(Path(p).name for p, _ in st.failed) == ["a.txt", "b.txt", "c.txt"]
    assert phone_files(phone, "/sdcard/Android") == {}
    assert read_tmp_folders("FAKE", directory=tmp_dir) == []
    assert st.done_files == 0


def test_verify_hash_mismatch_recopied_once_then_verified(phone, adb, pc, make_queue):
    put(phone, "/sdcard/P/a.jpg", b"good")
    put(phone, "/sdcard/P/b.jpg", b"fine")
    hits = {"n": 0}

    def corrupt(cmd: str) -> None:  # telefon zmienia bajty przy pierwszym sprawdzeniu (ten sam rozmiar)
        if cmd.startswith("sha256sum ") and "a.jpg" in cmd:
            hits["n"] += 1
            if hits["n"] == 1:
                phone.local("/sdcard/P/a.jpg").write_bytes(b"evil")

    phone.on_shell = corrupt
    plan = plan_to_pc(adb, ["/sdcard/P"], pc, **OK)
    q = make_queue()
    st = q.wait_for(q.add(plan, verify_hash=True), "done")
    assert st.verified == "hash" and st.failed == []  # druga kopia zgodna: bez „uszkodzonych”
    assert (st.done_files, st.total_files) == (2, 2)
    assert pc_files(pc) == {"P/a.jpg": b"evil", "P/b.jpg": b"fine"}
    assert phone.pulled.count("/sdcard/P/a.jpg") == 2 and phone.pulled.count("/sdcard/P/b.jpg") == 1
    assert not any(p.name.endswith(".admenot-part") for p in pc.rglob("*"))


def test_verify_hash_mismatch_twice_marked_damaged(phone, adb, pc, make_queue):
    put(phone, "/sdcard/P/a.jpg", b"good")
    put(phone, "/sdcard/P/b.jpg", b"fine")
    hits = {"n": 0}

    def corrupt(cmd: str) -> None:  # bajty zmieniają się przy każdym sprawdzeniu
        if cmd.startswith("sha256sum ") and "a.jpg" in cmd:
            hits["n"] += 1
            phone.local("/sdcard/P/a.jpg").write_bytes(f"ev{hits['n']:02d}".encode())

    phone.on_shell = corrupt
    plan = plan_to_pc(adb, ["/sdcard/P"], pc, **OK)
    q = make_queue()
    st = q.wait_for(q.add(plan, verify_hash=True), "done")
    assert st.verified == "mismatch"
    assert st.failed == [("/sdcard/P/a.jpg", "mismatch")]
    assert phone.pulled.count("/sdcard/P/a.jpg") == 2  # jedna automatyczna ponowna kopia, nie więcej
    assert pc_files(pc) == {"P/b.jpg": b"fine"}  # uszkodzona kopia nie zostaje pod docelową nazwą


def test_upload_hash_mismatch_reuploaded_once(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"a.bin": b"good", "b.bin": b"fine"})
    phone.local("/sdcard/Up").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / "a.bin", src / "b.bin"], "/sdcard/Up")
    pusher = NamedPusher(phone)
    mode = {"always": False, "hits": 0}

    def corrupt(cmd: str) -> None:  # karta psuje wgrany plik `a.bin` (ten sam rozmiar)
        if not cmd.startswith("sha256sum ") or not TMP_ON_PHONE.search(cmd):
            return
        tmp = cmd.split(" ", 1)[1].strip("'")
        if pusher.by_tmp.get(tmp) == "a.bin":
            mode["hits"] += 1
            if mode["always"] or mode["hits"] == 1:
                phone.local(tmp).write_bytes(b"BAD!")

    phone.on_shell = corrupt
    q = make_queue(pusher=pusher)
    st = q.wait_for(q.add(plan, verify_hash=True), "done")
    assert st.verified == "hash" and st.failed == [] and st.done_files == 2
    assert phone_files(phone, "/sdcard/Up") == {"a.bin": b"good", "b.bin": b"fine"}
    assert pusher.names.count("a.bin") == 2 and pusher.names.count("b.bin") == 1
    assert no_phone_tmp(phone)
    # psuje się za każdym razem: plik uszkodzony, na telefonie nic po nim nie zostaje
    mode["always"] = True
    phone.local("/sdcard/Up2").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / "a.bin", src / "b.bin"], "/sdcard/Up2")
    pusher.names.clear()
    st = q.wait_for(q.add(plan, verify_hash=True), "done")
    assert st.verified == "mismatch" and st.failed == [(str(src / "a.bin"), "mismatch")]
    assert pusher.names.count("a.bin") == 2
    assert phone_files(phone, "/sdcard/Up2") == {"b.bin": b"fine"} and no_phone_tmp(phone)


class NamedPusher:
    """Pusher atrapy, który pamięta, który plik lokalny trafił do którego pliku tymczasowego."""

    def __init__(self, phone: FakeStoragePhone) -> None:
        self.phone = phone
        self.names: list[str] = []
        self.by_tmp: dict[str, str] = {}

    def push(self, locals_, remote, should_stop, tick):
        self.names.append(locals_[0].name)
        self.by_tmp[remote] = locals_[0].name
        return self.phone.push(locals_, remote, should_stop, tick)


def test_media_scan_after_upload(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"a.jpg": b"j", "b.mp4": b"m", "c.txt": b"t", "d.mp3": b"s"})
    phone.local("/sdcard/Up").mkdir(parents=True)
    names = [src / n for n in ("a.jpg", "b.mp4", "c.txt", "d.mp3")]
    q = make_queue()
    q.wait_for(q.add(plan_to_phone(adb, names, "/sdcard/Up")), "done")
    assert sorted(phone.scanned) == ["/storage/emulated/0/Up/a.jpg", "/storage/emulated/0/Up/b.mp4",
                                     "/storage/emulated/0/Up/d.mp3"]
    phone.scanned.clear()
    phone.local("/sdcard/Old").mkdir(parents=True)
    old = make_queue(sdk=lambda: 28)
    old.wait_for(old.add(plan_to_phone(adb, names, "/sdcard/Old")), "done")
    assert phone.scanned == [] and phone.scans == 0


def test_events_throttled(phone, adb, pc, make_queue):
    for i in range(12):
        put(phone, f"/sdcard/P/f{i}.bin", b"x" * 10)
    plan = plan_to_pc(adb, ["/sdcard/P"], pc, **OK)
    events = Events()
    q = make_queue(emit=events, clock=Clock(step=0.0))  # zegar stoi: tylko zmiany statusu
    tid = q.add(plan)
    q.wait_for(tid, "done")
    assert events.statuses(tid) == ["queued", "running", "done"]
    assert all(n == "explorer:task" for n, _ in events.items)
    last = events.items[-1][1]
    assert last["done_files"] == 12 and last["status"] == "done" and isinstance(last["failed"], list)
    # zegar idzie po 1 s na odczyt: zdarzenia postępu co plik
    events2 = Events()
    pc2 = pc / "second"
    pc2.mkdir()
    q2 = make_queue(emit=events2, clock=Clock(step=1.0))
    tid2 = q2.add(plan_to_pc(adb, ["/sdcard/P"], pc2, **OK))
    q2.wait_for(tid2, "done")
    progress = [p["done_files"] for _, p in events2.items if p["status"] == "running"]
    assert len(progress) > 3 and progress == sorted(progress)


def test_sweep_tmp_removes_only_own_tmp_files(phone, adb):
    for name in (".admenot-0123456789ab.part", ".admenot-x.part", "zdjęcie.jpg.part", "a.jpg"):
        put(phone, f"/sdcard/Up/{name}")
    put(phone, "/sdcard/Up/sub/.admenot-0123456789ab.part")
    phone.local("/sdcard/Up/.admenot-abcdefabcdef.part").mkdir()  # folder o takiej nazwie — nie nasz plik
    n = sweep_tmp(adb, ["/sdcard/Up", "/sdcard/Missing"])
    assert n == 1
    assert sorted(phone_files(phone, "/sdcard/Up")) == [
        ".admenot-x.part", "a.jpg", "sub/.admenot-0123456789ab.part", "zdjęcie.jpg.part"]
    assert phone.local("/sdcard/Up/.admenot-abcdefabcdef.part").is_dir()
    assert [c for c in phone.commands if c.startswith("rm ")] == ["rm -f /sdcard/Up/.admenot-0123456789ab.part"]


def test_program_killed_mid_upload_swept_on_next_open(phone, adb, tmp_path, make_queue, tmp_dir):
    src = tmp_path / "src"
    local_tree(src, {"a.bin": b"a" * 20})
    phone.local("/sdcard/Up").mkdir(parents=True)
    entered, release = threading.Event(), threading.Event()

    class HangingPusher:  # proces zabity w połowie pliku: na telefonie połówka, na dysku wpis folderu
        def push(self, locals_, remote, should_stop, tick):
            phone.local(remote).write_bytes(locals_[0].read_bytes()[:10])
            entered.set()
            release.wait(10)
            return PullResult(1, [], True)

    q = make_queue(pusher=HangingPusher())
    tid = q.add(plan_to_phone(adb, [src / "a.bin"], "/sdcard/Up"))
    assert entered.wait(10)
    # stan „zabitego” procesu: folder zapisany na dysku przed `push`, połówka pod nazwą tymczasową
    assert read_tmp_folders("FAKE", directory=tmp_dir) == ["/sdcard/Up"]
    assert [is_tmp_name(p.name) for p in phone.local("/sdcard/Up").iterdir()] == [True]
    # następne otwarcie eksploratora (nowy proces) czyta listę z dysku i sprząta
    assert sweep_recorded(adb, "FAKE", directory=tmp_dir) == 1
    assert phone_files(phone, "/sdcard/Up") == {}
    assert read_tmp_folders("FAKE", directory=tmp_dir) == []
    record_tmp_folder("FAKE", "/sdcard/Gone", directory=tmp_dir)  # folder, którego już nie ma
    assert sweep_recorded(adb, "FAKE", directory=tmp_dir) == 0
    assert read_tmp_folders("FAKE", directory=tmp_dir) == []
    q.cancel(tid)
    release.set()
    q.wait_for(tid, "cancelled")


# ---- poprawki po przeglądzie (runda 1) ------------------------------------------------------------


def test_refused_tmp_cleanup_while_online_does_not_loop(phone, adb, tmp_path, make_queue, tmp_dir):
    src = tmp_path / "src"
    files = {"a.bin": b"a" * 30, "b.bin": b"b" * 30, "c.bin": b"c" * 30}
    local_tree(src, files)
    phone.local("/sdcard/Up").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / n for n in files], "/sdcard/Up")

    def refuse_rm(cmd: str) -> None:  # telefon jest, ale `rm -f` odmawia
        if cmd.startswith("rm "):
            raise AdbError("command_failed", "rm: /sdcard/Up/x: Permission denied")

    phone.on_shell = refuse_rm
    phone.fail_after_push_files = 1
    events = Events()
    q = make_queue(emit=events)
    tid = q.add(plan)
    q.wait_for(tid, "waiting")
    phone.fail_after_push_files = None
    phone.reconnect()
    st = q.wait_for(tid, "done")
    assert events.statuses(tid).count("waiting") == 1  # bez pętli running/waiting
    assert st.done_files == 3 and st.failed == []
    assert {k: v for k, v in phone_files(phone, "/sdcard/Up").items() if not is_tmp_name(k)} == files
    assert not no_phone_tmp(phone)  # połówka została na telefonie…
    assert read_tmp_folders("FAKE", directory=tmp_dir) == ["/sdcard/Up"]  # …a folder na liście do sprzątnięcia


def test_hash_timeout_scales_with_size():
    assert hash_timeout(0) == HASH_BASE_TIMEOUT
    assert hash_timeout(4 * 1024**3) >= HASH_BASE_TIMEOUT + 4 * 1024**3 / HASH_MIN_SPEED
    assert hash_timeout(4 * 1024**3) > 200  # plik 4 GB: kilka minut, nie stałe 60 s


def test_pc_target_appearing_before_commit_kept(phone, adb, pc, make_queue):
    put(phone, "/sdcard/P/a.jpg", b"phone")
    plan = plan_to_pc(adb, ["/sdcard/P/a.jpg"], pc, **OK)
    assert plan.items[0].action == "copy"

    class RacingPuller:  # klient zapisuje plik o tej nazwie, zanim pobrany dostanie docelową nazwę
        def pull(self, remotes, target, should_stop, tick):
            res = phone.pull(remotes, target, should_stop, tick)
            (pc / "a.jpg").write_bytes(b"client")
            return res

    q = make_queue(puller=RacingPuller())
    st = q.wait_for(q.add(plan), "done")
    assert pc_files(pc) == {"a.jpg": b"client", "a (z telefonu).jpg": b"phone"}
    assert st.renamed == 1 and st.done_files == 1


def test_pc_target_appearing_after_existence_check_kept(phone, adb, pc, make_queue, monkeypatch):
    put(phone, "/sdcard/P/b.jpg", b"phone")
    plan = plan_to_pc(adb, ["/sdcard/P/b.jpg"], pc, **OK)
    target = str(pc / "b.jpg")
    real_lexists, real_rename = os.path.lexists, os.rename

    def appear() -> None:
        if not real_lexists(target):
            (pc / "b.jpg").write_bytes(b"client")

    def racing_lexists(path) -> bool:  # plik pojawia się tuż po sprawdzeniu, przed zmianą nazwy
        found = real_lexists(path)
        if str(path) == target:
            appear()
        return found

    def racing_rename(src, dst) -> None:  # … albo w chwili samej zmiany nazwy
        if str(dst) == target:
            appear()
        real_rename(src, dst)

    monkeypatch.setattr(os.path, "lexists", racing_lexists)
    monkeypatch.setattr(os, "rename", racing_rename)
    q = make_queue()
    st = q.wait_for(q.add(plan), "done")
    assert pc_files(pc) == {"b.jpg": b"client", "b (z telefonu).jpg": b"phone"}
    assert st.renamed == 1


def test_emit_callback_can_read_tasks(phone, adb, pc, make_queue):
    for i in range(3):
        put(phone, f"/sdcard/P/f{i}.bin", b"x" * 5)
    plan = plan_to_pc(adb, ["/sdcard/P"], pc, **OK)
    holder: dict = {"stuck": 0, "seen": 0}

    def emit(name: str, payload: dict) -> None:  # mostek odczytuje kolejkę z innego wątku i czeka
        if "q" not in holder:
            return
        t = threading.Thread(target=lambda: holder.__setitem__("seen", len(holder["q"].tasks())))
        t.start()
        t.join(5)
        holder["stuck"] += t.is_alive()

    q = make_queue(emit=emit)
    holder["q"] = q
    q.wait_for(q.add(plan), "done")
    assert holder["stuck"] == 0 and holder["seen"] == 1


def test_copy_to_pc_keeps_tricky_names(phone, adb, pc, make_queue):
    # Review Focus 1: myślnik na początku, `$`, polskie znaki, apostrof, emoji — nazwy bez zmian na PC
    names = ["-a.jpg", "$x zażółć.jpg", "it's Ola.jpg", "🎉 urodziny 😀.jpg"]
    for i, name in enumerate(names):
        put(phone, f"/sdcard/Pics/{name}", bytes([65 + i]) * (i + 1))
    plan = plan_to_pc(adb, ["/sdcard/Pics"], pc, **OK)
    q = make_queue()
    st = q.wait_for(q.add(plan, verify_hash=True), "done")
    assert pc_files(pc) == {f"Pics/{name}": bytes([65 + i]) * (i + 1) for i, name in enumerate(names)}
    assert sorted(os.listdir(pc / "Pics")) == sorted(names)
    assert st.failed == [] and st.renamed == 0 and st.verified == "hash"


def test_offline_in_folder_name_with_mkdir_failure_fails_the_file(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"Mapy offline/plan.txt": b"p"})
    phone.local("/sdcard/Download").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / "Mapy offline"], "/sdcard/Download")

    def refuse(cmd: str) -> None:  # tekst błędu z „offline” → adb mówi rodzaj `offline`, telefon jest
        if cmd.startswith("mkdir "):
            raise classify_error("mkdir: '/sdcard/Download/Mapy offline': Permission denied")

    phone.on_shell = refuse
    events = Events()
    q = make_queue(emit=events)
    tid = q.add(plan)
    st = q.wait_for(tid, "done", timeout=10)
    assert st.failed == [(str(src / "Mapy offline" / "plan.txt"), "denied")]
    assert "waiting" not in events.statuses(tid)
    assert phone.push_calls == 0 and no_phone_tmp(phone)


def test_directory_with_target_name_gets_name_beside(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"a.jpg": b"mine"})
    phone.local("/sdcard/Up").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / "a.jpg"], "/sdcard/Up")
    assert plan.items[0].action == "copy"

    class DirAppears:  # klient tworzy folder o nazwie celu w trakcie wgrywania
        def push(self, locals_, remote, should_stop, tick):
            phone.local("/sdcard/Up/a.jpg").mkdir(exist_ok=True)
            return phone.push(locals_, remote, should_stop, tick)

    q = make_queue(pusher=DirAppears())
    st = q.wait_for(q.add(plan), "done")
    assert phone.local("/sdcard/Up/a.jpg").is_dir()
    assert list(phone.local("/sdcard/Up/a.jpg").iterdir()) == []  # `mv -n` nie wsunął pliku do folderu
    assert phone_files(phone, "/sdcard/Up") == {"a (z komputera).jpg": b"mine"}
    assert st.renamed == 1 and st.done_files == 1 and st.failed == []
    assert not any(c.startswith("mv -n ") and c.endswith("/sdcard/Up/a.jpg'") for c in phone.commands)


def test_queue_pushes_only_through_the_explorer_guard(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"a.jpg": b"a", "b.jpg": b"b"})
    phone.local("/sdcard/Up").mkdir(parents=True)
    q = make_queue()
    assert isinstance(q._pusher, ExplorerPusher) and q._pusher.inner is phone
    st = q.wait_for(q.add(plan_to_phone(adb, [src / "a.jpg"], "/sdcard/Up")), "done")
    assert st.done_files == 1 and all(TMP_ON_PHONE.fullmatch(p.rsplit("/", 1)[1]) for p in phone.pushed)
    # token spoza wzorca: nic nie idzie do `adb push`
    bad = make_queue(token=lambda: "../../x")
    st = bad.wait_for(bad.add(plan_to_phone(adb, [src / "b.jpg"], "/sdcard/Up")), "done")
    assert st.failed == [(str(src / "b.jpg"), "error")] and phone.push_calls == 1


# ---- poprawki po przeglądzie 2026-11-06 ---------------------------------------------------------


def test_items_the_plan_could_not_read_are_not_counted_as_identical(phone, adb, pc, make_queue):
    put(phone, "/sdcard/jest.txt")
    plan = plan_to_pc(adb, ["/sdcard/zniknal.txt"], pc, **OK)
    q = make_queue()
    st = q.wait_for(q.add(plan), "done")
    assert st.skipped == 0 and st.omitted == 1


def test_identical_file_in_queue_twice_is_skipped_not_saved_beside(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"a.bin": b"same"})
    phone.local("/sdcard/Up").mkdir(parents=True)
    first = plan_to_phone(adb, [src / "a.bin"], "/sdcard/Up")
    second = plan_to_phone(adb, [src / "a.bin"], "/sdcard/Up")  # liczony, zanim pierwszy się wykonał
    q = make_queue()
    q.wait_for(q.add(first), "done")
    st = q.wait_for(q.add(second), "done")
    assert phone_files(phone, "/sdcard/Up") == {"a.bin": b"same"}
    assert st.skipped == 1 and st.renamed == 0 and no_phone_tmp(phone)


def test_different_file_appearing_during_upload_still_goes_beside(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"a.bin": b"mine"})
    phone.local("/sdcard/Up").mkdir(parents=True)
    plan = plan_to_phone(adb, [src / "a.bin"], "/sdcard/Up")
    put(phone, "/sdcard/Up/a.bin", b"them")  # ten sam rozmiar, inna treść
    q = make_queue()
    st = q.wait_for(q.add(plan), "done")
    assert phone_files(phone, "/sdcard/Up") == {"a.bin": b"them", "a (z komputera).bin": b"mine"}
    assert st.renamed == 1


def test_identical_file_on_pc_in_queue_twice_is_skipped(phone, adb, pc, make_queue):
    put(phone, "/sdcard/a.bin", b"same")
    first = plan_to_pc(adb, ["/sdcard/a.bin"], pc, **OK)
    second = plan_to_pc(adb, ["/sdcard/a.bin"], pc, **OK)
    q = make_queue()
    q.wait_for(q.add(first), "done")
    st = q.wait_for(q.add(second), "done")
    assert pc_files(pc) == {"a.bin": b"same"}
    assert st.skipped == 1 and st.renamed == 0


def test_pause_answers_at_once_during_phone_hash(phone, adb, pc, make_queue):
    put(phone, "/sdcard/a.bin", b"data")
    release = threading.Event()
    holder: dict[str, str] = {}

    def slow(cmd: str) -> None:  # `sha256sum` wielkiego pliku trwa minutami
        if cmd.startswith("sha256sum "):
            q.pause(holder["id"])
            release.wait(10)

    phone.on_shell = slow
    plan = plan_to_pc(adb, ["/sdcard/a.bin"], pc, **OK)
    q = make_queue()
    holder["id"] = tid = q.add(plan, verify_hash=True)
    try:
        st = q.wait_for(tid, "paused", timeout=3)
        assert st.failed == []  # przerwane, nie nieudane
        assert pc_files(pc) == {}  # plik w toku nie zostaje
    finally:
        release.set()


def test_part_file_folder_is_on_disk_during_copy_and_forgotten_after(phone, adb, pc, tmp_dir, make_queue):
    put(phone, "/sdcard/a.bin", b"data")
    seen: list[list[str]] = []

    class Spy:
        def pull(self, remotes, target, should_stop, tick):
            seen.append(read_part_folders(directory=tmp_dir))
            return phone.pull(remotes, target, should_stop, tick)

    q = make_queue(puller=Spy())
    q.wait_for(q.add(plan_to_pc(adb, ["/sdcard/a.bin"], pc, **OK)), "done")
    assert len(seen) == 1 and len(seen[0]) == 1 and seen[0][0].endswith(pc.name)
    assert read_part_folders(directory=tmp_dir) == []


def test_sweep_removes_only_our_parts_from_recorded_folders(tmp_path, tmp_dir):
    folder = tmp_path / "dest"
    folder.mkdir()
    (folder / "film.mp4.admenot-part").write_bytes(b"pol pliku")
    (folder / "film.mp4").write_bytes(b"plik klienta")
    other = tmp_path / "other"
    other.mkdir()
    (other / "obcy.admenot-part").write_bytes(b"nie z listy")
    record_part_folder(str(folder), directory=tmp_dir)
    assert sweep_parts(directory=tmp_dir) == 1
    assert sorted(p.name for p in folder.iterdir()) == ["film.mp4"]
    assert (other / "obcy.admenot-part").exists()
    assert read_part_folders(directory=tmp_dir) == []


def test_sweep_skips_folders_of_a_live_queue(tmp_path, tmp_dir):
    folder = tmp_path / "dest"
    folder.mkdir()
    (folder / "x.admenot-part").write_bytes(b"w toku")
    record_part_folder(str(folder), directory=tmp_dir)
    assert sweep_parts(directory=tmp_dir, skip={str(folder)}) == 0
    assert (folder / "x.admenot-part").exists()
    assert read_part_folders(directory=tmp_dir) == [str(folder)]


def test_upload_shows_progress_inside_one_big_file(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"film.bin": b"F" * 1000})
    phone.local("/sdcard/Up").mkdir(parents=True)
    seen: list[int] = []

    class Half:
        def push(self, locals_, remote, should_stop, tick):
            phone.local(remote).write_bytes(b"F" * 400)
            tick()
            seen.append(q.tasks()[0].done_bytes)
            return phone.push(locals_, remote, should_stop, tick)

    q = make_queue(pusher=Half(), progress_min=100, progress_interval=0)
    st = q.wait_for(q.add(plan_to_phone(adb, [src / "film.bin"], "/sdcard/Up")), "done")
    assert seen == [400]
    assert st.done_bytes == 1000  # bajty w toku nie liczą się podwójnie


def test_closing_with_a_paused_upload_removes_its_tmp(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"big.bin": b"B" * 400})
    phone.local("/sdcard/Up").mkdir(parents=True)
    q = make_queue(big_file=100)
    tid = q.add(plan_to_phone(adb, [src / "big.bin"], "/sdcard/Up"))
    q.wait_for(tid, "done")
    leftover = "/sdcard/Up/.admenot-0123456789ab.part"
    put(phone, leftover, b"x")
    task = q._tasks[tid]
    task.tmps.add(leftover)
    task.state.status = "paused"
    q.shutdown()
    assert no_phone_tmp(phone)


def test_retry_runs_only_the_failed_files_again(phone, adb, pc, make_queue):
    put(phone, "/sdcard/P/a.jpg", b"good")
    put(phone, "/sdcard/P/b.jpg", b"fine")
    state = {"bad": True}

    def corrupt(cmd: str) -> None:
        if cmd.startswith("sha256sum ") and "a.jpg" in cmd and state["bad"]:
            phone.local("/sdcard/P/a.jpg").write_bytes(os.urandom(4))

    phone.on_shell = corrupt
    q = make_queue()
    tid = q.add(plan_to_pc(adb, ["/sdcard/P"], pc, **OK), verify_hash=True)
    assert q.wait_for(tid, "done").verified == "mismatch"
    state["bad"] = False
    st = q.wait_for(q.retry(tid), "done")
    assert st.verified == "hash" and st.failed == [] and (st.done_files, st.total_files) == (1, 1)
    assert "P/a.jpg" in pc_files(pc)
    assert q.retry("nie-ma") is None


def test_retry_of_task_without_failures_does_nothing(phone, adb, pc, make_queue):
    put(phone, "/sdcard/a.bin", b"x")
    q = make_queue()
    tid = q.add(plan_to_pc(adb, ["/sdcard/a.bin"], pc, **OK))
    q.wait_for(tid, "done")
    assert q.retry(tid) is None


def test_finished_upload_lists_where_the_files_landed(phone, adb, tmp_path, make_queue):
    src = tmp_path / "src"
    local_tree(src, {"a.bin": b"new", "b.bin": b"same"})
    put(phone, "/sdcard/Up/b.bin", b"same")
    plan = plan_to_phone(adb, [src / "a.bin", src / "b.bin"], "/sdcard/Up")
    q = make_queue()
    st = q.wait_for(q.add(plan), "done")
    assert sorted(st.targets) == ["/sdcard/Up/a.bin", "/sdcard/Up/b.bin"]  # także pominięty identyczny: „Pokaż” go wskaże


def test_copy_to_pc_lists_no_phone_targets(phone, adb, pc, make_queue):
    put(phone, "/sdcard/a.bin", b"x")
    q = make_queue()
    assert q.wait_for(q.add(plan_to_pc(adb, ["/sdcard/a.bin"], pc, **OK)), "done").targets == []
