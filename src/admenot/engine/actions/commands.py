"""Polecenia ADB akcji (spec §7). Jedno miejsce, z którego korzystają kroki i FakePhone w testach.

Wartości, które mogą zawierać `$` (nazwy komponentów), są w pojedynczym cudzysłowie —
bez niego powłoka telefonu potraktuje `$ListenerService` jako zmienną i ją wytnie. Wstawiamy je
przez `quoted()`: apostrof w środku nie zamknie cudzysłowu (audyt 2026-10-11, SEC-01).
"""


def quoted(value: str) -> str:
    """Treść do wstawienia między '…' w poleceniu powłoki POSIX (apostrof → '"'"')."""
    return value.replace("'", "'\"'\"'")


FORCE_STOP = "am force-stop {package}"
# Jawny profil 0 (skanowany), jak przy disable/uninstall (audyt 2026-10-11, BUG-08); bez niego
# polecenie trafia do bieżącego użytkownika, którym na telefonie z drugą przestrzenią może być
# inny profil. Sprawdzone na OPPO CPH2271 (Android 12, ColorOS) 2026-10-11.
APPOPS_GET_OP = "appops get --user 0 {package} {op}"
APPOPS_SET = "appops set --user 0 {package} {op} {mode}"
PM_GRANT = "pm grant --user 0 {package} {permission}"
PM_REVOKE = "pm revoke --user 0 {package} {permission}"
DUMPSYS_PACKAGE = "dumpsys package {package}"
SETTINGS_GET = "settings get --user 0 secure {key}"
SETTINGS_PUT = "settings put --user 0 secure {key} '{value}'"
# user_id jest tu pozycyjny, po komponencie; allow | disallow
NOTIF_LISTENER = "cmd notification {action}_listener '{component}' 0"
DEFAULT_IME = SETTINGS_GET.format(key="default_input_method")
SET_HOME = "cmd package set-home-activity --user 0 '{component}'"
PM_DISABLE = "pm disable-user --user 0 {package}"
PM_ENABLE = "pm enable --user 0 {package}"
PM_INSTALLED = "pm list packages --user 0 {package}"
PM_UNINSTALL = "pm uninstall --user 0 {package}"
PM_INSTALL_EXISTING = "cmd package install-existing --user 0 {package}"
ADMIN_SETTINGS = "am start -n 'com.android.settings/.Settings$DeviceAdminSettingsActivity'"
SECURITY_SETTINGS = "am start -a android.settings.SECURITY_SETTINGS"
GETPROP_SDK = "getprop ro.build.version.sdk"
INSTALL_TIMEOUT = 300.0
