from pathlib import Path

ISS = Path(__file__).resolve().parents[1] / "packaging" / "admenot.iss"


def test_installer_script_keeps_its_identity_and_encoding():
    raw = ISS.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "ISCC czyta polskie znaki poprawnie tylko z BOM"
    text = raw.decode("utf-8-sig")
    assert "AppId={{77236DB7-7708-4AE0-9E40-95112CFFB4DB}" in text  # nigdy się nie zmienia
    assert "PrivilegesRequired=lowest" in text
    assert 'Name: "{app}\\_internal"' in text  # [InstallDelete] przed aktualizacją
    assert "UninstallSilent" in text  # tryb cichy nigdy nie kasuje danych


def test_update_install_restarts_the_program():
    text = ISS.read_bytes().decode("utf-8-sig")
    run = text.split("[Run]", 1)[1].split("[", 1)[0]
    lines = [line for line in run.splitlines() if line.strip()]
    restart = [line for line in lines if "Check: IsUpdate" in line]
    assert len(restart) == 1 and "nowait" in restart[0] and "postinstall" not in restart[0]
    assert any("postinstall skipifsilent" in line for line in lines)  # ręczna instalacja bez zmian
    assert "function IsUpdate: Boolean;" in text and "'/UPDATE=1'" in text
