import threading

from admenot.app.watcher import DeviceWatcher


def test_poll_once_emits_only_changes_and_respects_pause():
    lists = [{"devices": []}, {"devices": []}, {"devices": [{"serial": "S1"}]}]
    sent, paused = [], [False]
    watcher = DeviceWatcher(lambda: lists.pop(0), sent.append, paused=lambda: paused[0])
    assert watcher.poll_once() is True
    assert watcher.poll_once() is False
    paused[0] = True
    assert watcher.poll_once() is False and len(lists) == 1
    paused[0] = False
    assert watcher.poll_once() is True
    assert sent == [{"devices": []}, {"devices": [{"serial": "S1"}]}]


def test_thread_polls_until_stopped_and_restart_resends():
    sent = []
    got = threading.Event()

    def emit(payload):
        sent.append(payload)
        got.set()

    watcher = DeviceWatcher(lambda: {"devices": []}, emit, interval=0.01)
    watcher.start()
    watcher.start()
    assert got.wait(2) and watcher.running
    watcher.stop()
    for _ in range(200):
        if not watcher.running:
            break
        threading.Event().wait(0.01)
    assert not watcher.running and sent == [{"devices": []}]
    got.clear()
    watcher.start()
    assert got.wait(2) and len(sent) == 2
    watcher.stop()


def test_errors_in_list_fn_do_not_kill_the_thread():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("adb hiccup")
        return {"devices": []}

    got = threading.Event()
    watcher = DeviceWatcher(flaky, lambda p: got.set(), interval=0.01)
    watcher.start()
    assert got.wait(2)
    watcher.stop()
