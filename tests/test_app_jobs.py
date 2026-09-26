import threading

import pytest

from demalware.app.errors import AppError
from demalware.app.events import RecordingEmitter
from demalware.app.jobs import JobRunner, Stopped


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_sync_job_runs_inline_and_ends():
    rec = RecordingEmitter()
    runner = JobRunner(rec, sync=True)
    job_id = runner.start("scan", lambda job: rec.emit("work", {"id": job.id}))
    assert job_id == "job-1"
    assert rec.events == [("work", {"id": "job-1"}), ("job:end", {"job_id": "job-1", "kind": "scan"})]
    assert runner.current() is None
    assert runner.start("scan", lambda job: None) == "job-2"


def test_errors_are_reported_before_the_end():
    rec = RecordingEmitter()
    runner = JobRunner(rec, sync=True)

    def fail(job):
        raise AppError("no_scan")

    runner.start("exec", fail)
    assert rec.names() == ["job:error", "job:end"]
    assert rec.of("job:error")[0] == {"job_id": "job-1", "kind": "exec", "key": "no_scan",
                                      "message": ""}

    def crash(job):
        raise RuntimeError("boom")

    runner.start("exec", crash)
    error = rec.of("job:error")[1]
    assert error["key"] == "internal" and "boom" in error["message"] and error["log"]


def test_busy_stop_and_wait():
    rec = RecordingEmitter()
    runner = JobRunner(rec)
    started = threading.Event()

    def loop(job):
        started.set()
        while True:
            job.check()
            job.done.wait(0.01)

    runner.start("apk", loop)
    started.wait(2)
    with pytest.raises(AppError) as info:
        runner.start("exec", lambda job: None)
    assert info.value.key == "busy" and info.value.message == "apk"
    assert runner.stop("job-other") is False
    assert runner.stop("job-1") is True
    assert runner.wait(2) is True
    assert runner.current() is None
    assert "job:error" not in rec.names() and rec.of("job:end") == [{"job_id": "job-1", "kind": "apk"}]


def test_ask_waits_for_answer_and_returns_none_after_stop():
    rec = RecordingEmitter()
    runner = JobRunner(rec)
    answers = []
    runner.start("exec", lambda job: answers.append(job.ask("exec:question", {"package": "p"})))
    question = rec.wait_for("exec:question")
    assert question == {"job_id": "job-1", "package": "p"}
    assert runner.answer("job-1", "retry") is True
    runner.wait(2)
    assert answers == ["retry"]

    runner.start("exec", lambda job: answers.append(job.ask("exec:question", {"package": "q"})))
    rec.wait_for("exec:question")
    runner.stop("job-2")
    runner.wait(2)
    assert answers == ["retry", None]


def test_abandon_frees_the_runner_at_once():
    rec = RecordingEmitter()
    runner = JobRunner(rec)
    release = threading.Event()
    stopped_seen = []

    def slow(job):
        release.wait(2)
        stopped_seen.append(job.should_stop())

    runner.start("apk", slow)
    assert runner.abandon("job-1") is True
    assert runner.current() is None
    runner.start("exec", lambda job: None)
    runner.wait(2)
    release.set()
    rec.wait_for("job:end")
    for _ in range(200):
        if stopped_seen:
            break
        threading.Event().wait(0.01)
    assert stopped_seen == [True]
    assert runner.current() is None


def test_check_raises_stopped():
    rec = RecordingEmitter()
    runner = JobRunner(rec, sync=True)
    seen = []

    def body(job):
        runner.stop(job.id)
        try:
            job.check()
        except Stopped:
            seen.append("stopped")
            raise

    runner.start("scan", body)
    assert seen == ["stopped"] and "job:error" not in rec.names()
