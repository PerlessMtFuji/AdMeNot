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
