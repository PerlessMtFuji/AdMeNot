import subprocess
from pathlib import Path

import pytest

from demalware.engine.report import pdf as pdf_mod
from demalware.engine.report.pdf import PdfError, edge_command, find_edge, html_to_pdf


class FakeRun:
    def __init__(self, output=b"%PDF-1.4\n%fake\n", exc=None):
        self.output, self.exc = output, exc
        self.cmd, self.kw = None, None

    def __call__(self, cmd, **kw):
        self.cmd, self.kw = cmd, kw
        if self.exc is not None:
            raise self.exc
        target = next(a.split("=", 1)[1] for a in cmd if a.startswith("--print-to-pdf="))
        if self.output is not None:
            Path(target).write_bytes(self.output)
        return subprocess.CompletedProcess(cmd, 0)


@pytest.fixture
def files(tmp_path):
    html = tmp_path / "Zlecenie ą.html"
    html.write_text("<!doctype html><p>ok</p>", "utf-8")
    edge = tmp_path / "msedge.exe"
    edge.write_bytes(b"")
    return html, tmp_path / "out" / "p.pdf", edge


def leftovers(pdf: Path) -> list[Path]:
    return list(pdf.parent.glob("*.tmp.pdf")) if pdf.parent.exists() else []


def test_prints_through_edge(files):
    html, pdf, edge = files
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-old")
    run = FakeRun()
    html_to_pdf(html, pdf, edge=edge, run=run)
    assert pdf.read_bytes().startswith(b"%PDF-1.4") and not leftovers(pdf)
    assert run.cmd[0] == str(edge) and "--headless" in run.cmd
    assert "--no-pdf-header-footer" in run.cmd
    assert run.cmd[-1] == html.resolve().as_uri()
    assert any(a.startswith("--user-data-dir=") for a in run.cmd)
    assert run.kw["timeout"] == 60.0 and run.kw["check"] is False
    assert run.kw["stdout"] == subprocess.DEVNULL and run.kw["stdin"] == subprocess.DEVNULL


def test_edge_command_uses_a_private_profile(tmp_path):
    cmd = edge_command(Path("C:/e/msedge.exe"), tmp_path / "a.html", tmp_path / "a.pdf",
                       tmp_path / "prof")
    assert f"--user-data-dir={tmp_path / 'prof'}" in cmd
    assert f"--print-to-pdf={tmp_path / 'a.pdf'}" in cmd


def test_no_browser(files, monkeypatch):
    html, pdf, _ = files
    monkeypatch.setattr(pdf_mod, "find_edge", lambda: None)
    with pytest.raises(PdfError) as exc:
        html_to_pdf(html, pdf, run=FakeRun())
    assert exc.value.key == "no_browser"


@pytest.mark.parametrize(("run", "key"), [
    (FakeRun(exc=subprocess.TimeoutExpired("msedge", 60)), "timeout"),
    (FakeRun(exc=OSError("boom")), "failed"),
    (FakeRun(output=None), "failed"),
    (FakeRun(output=b"<html>not a pdf"), "failed"),
])
def test_failures_keep_the_old_pdf(files, run, key):
    html, pdf, edge = files
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-old")
    with pytest.raises(PdfError) as exc:
        html_to_pdf(html, pdf, edge=edge, run=run)
    assert exc.value.key == key
    assert pdf.read_bytes() == b"%PDF-old" and not leftovers(pdf)


def test_locked_target(files, monkeypatch):
    html, pdf, edge = files
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-old")

    def locked(src, dst):
        raise PermissionError(13, "used by another process")

    monkeypatch.setattr(pdf_mod, "_replace", locked)
    with pytest.raises(PdfError) as exc:
        html_to_pdf(html, pdf, edge=edge, run=FakeRun())
    assert exc.value.key == "locked"
    assert pdf.read_bytes() == b"%PDF-old" and not leftovers(pdf)


def test_find_edge(tmp_path):
    installed = tmp_path / "PF86" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"")
    assert find_edge({"ProgramFiles(x86)": str(tmp_path / "PF86")}) == installed
    assert find_edge({"ProgramFiles": str(tmp_path / "none")}) is None
    custom = tmp_path / "edge.exe"
    custom.write_bytes(b"")
    assert find_edge({"DEMALWARE_EDGE": str(custom),
                      "ProgramFiles(x86)": str(tmp_path / "PF86")}) == custom
    assert find_edge({"DEMALWARE_EDGE": str(tmp_path / "missing.exe"),
                      "ProgramFiles(x86)": str(tmp_path / "PF86")}) is None


@pytest.mark.skipif(find_edge() is None, reason="Microsoft Edge nie jest zainstalowany")
def test_real_edge_prints_a4(tmp_path):
    html = tmp_path / "Zażółć.html"
    html.write_text("<!doctype html><meta charset='utf-8'><style>@page{size:A4}</style>"
                    "<h1>Zażółć gęślą jaźń</h1>", "utf-8")
    pdf = tmp_path / "out.pdf"
    html_to_pdf(html, pdf)
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF-") and b"/MediaBox [0 0 594.95996 841.91998]" in data
