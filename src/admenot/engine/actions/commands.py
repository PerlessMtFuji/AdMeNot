"""Polecenia ADB akcji (spec §7). Jedno miejsce, z którego korzystają kroki i FakePhone w testach.

Wartości, które mogą zawierać `$` (nazwy komponentów), są w pojedynczym cudzysłowie —
bez niego powłoka telefonu potraktuje `$ListenerService` jako zmienną i ją wytnie.
"""

FORCE_STOP = "am force-stop {package}"
APPOPS_GET_OP = "appops get {package} {op}"
APPOPS_SET = "appops set {package} {op} {mode}"
PM_GRANT = "pm grant {package} {permission}"
PM_REVOKE = "pm revoke {package} {permission}"
DUMPSYS_PACKAGE = "dumpsys package {package}"
SETTINGS_GET = "settings get secure {key}"
SETTINGS_PUT = "settings put secure {key} '{value}'"
NOTIF_LISTENER = "cmd notification {action}_listener '{component}'"  # allow | disallow
DEFAULT_IME =SETTINGS_GET.format(key="default_input_method")
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
