; Instalator AdMeNot (spec wydania §6). Buduje go scripts\build_release.py:
;   ISCC /DAppVersion=0.9.0 /DWinVersion=0.9.0.0 /DSourceDir=<dist\AdMeNot>
;        /DWebView2Setup=<build\MicrosoftEdgeWebview2Setup.exe> /O<dist\release>
;        /FAdMeNot-0.9.0-setup packaging\admenot.iss
; Podpis (opcjonalnie): /DSign /Sadmenot=<polecenie z $f w miejscu pliku>
; Plik musi zostać w UTF-8 z BOM — inaczej polskie znaki psują się w instalatorze.

#ifndef AppVersion
  #error Brak /DAppVersion — uruchom scripts\build_release.py
#endif

[Setup]
AppId={{77236DB7-7708-4AE0-9E40-95112CFFB4DB}
AppName=AdMeNot
AppVersion={#AppVersion}
AppPublisher=Eryk Wlodarski
AppCopyright=Copyright (c) Eryk Wlodarski
VersionInfoVersion={#WinVersion}
VersionInfoProductName=AdMeNot
DefaultDirName={autopf}\AdMeNot
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#SourcePath}..\src\admenot\assets\icon\admenot.ico
UninstallDisplayIcon={app}\AdMeNot.exe
UninstallDisplayName=AdMeNot
; AdMeNot zamyka użytkownik w PrepareToInstall; Restart Manager tylko domyka inne procesy
; trzymające pliki w {app} (np. podgląd w Eksploratorze)
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=auto
OutputDir={#SourcePath}..\dist\release
OutputBaseFilename=AdMeNot-{#AppVersion}-setup
#ifdef Sign
SignTool=admenot
#endif

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"

[CustomMessages]
pl.DeleteData=Usunąć też folder danych %LOCALAPPDATA%\AdMeNot (dziennik zleceń, ustawienia, protokoły, zrzuty ekranu, pamięć podręczna APK i zapisane tam kopie)?%n%nDziennik jest potrzebny, żeby cofnąć zmiany na telefonach klientów.
en.DeleteData=Also delete the AdMeNot data folder %LOCALAPPDATA%\AdMeNot (job journal, settings, reports, screenshots, APK cache and backups stored there)?%n%nThe journal is needed to undo changes on customers' phones.
pl.CloseApp=AdMeNot jest uruchomiony. Zamknij program i kliknij OK.
en.CloseApp=AdMeNot is running. Close the program and click OK.
pl.InstallCancelled=Instalacja przerwana — zamknij AdMeNot i uruchom instalator ponownie.
en.InstallCancelled=Setup cancelled — close AdMeNot and run Setup again.
pl.InstallingWebView2=Instalowanie Microsoft Edge WebView2 Runtime...
en.InstallingWebView2=Installing Microsoft Edge WebView2 Runtime...
pl.WebView2Failed=Nie udało się zainstalować Microsoft Edge WebView2 Runtime, którego AdMeNot potrzebuje do wyświetlenia okna. Zainstaluj go ze strony:%nhttps://developer.microsoft.com/microsoft-edge/webview2/
en.WebView2Failed=Microsoft Edge WebView2 Runtime, which AdMeNot needs for its window, could not be installed. Install it from:%nhttps://developer.microsoft.com/microsoft-edge/webview2/

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; pliki poprzedniej wersji nie mogą zostać obok nowych (spec §6.4)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebView2Setup}"; DestDir: "{tmp}"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\AdMeNot"; Filename: "{app}\AdMeNot.exe"
Name: "{autodesktop}\AdMeNot"; Filename: "{app}\AdMeNot.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AdMeNot.exe"; Description: "{cm:LaunchProgram,AdMeNot}"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2Key = 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function PowerShell(Command: String): Integer;
var
  ResultCode: Integer;
begin
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -ExecutionPolicy Bypass -Command "' + Command + '"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    ResultCode := -1;
  Result := ResultCode;
end;

function Quoted(Path: String): String;
begin
  { ścieżka w '...' dla PowerShell; apostrof w nazwie profilu podwajamy }
  StringChangeEx(Path, '''', '''''', True);
  Result := '''' + Path + '''';
end;

{ Spec §6.3: procesy z katalogu programu (adb, scrcpy, admenot-cli) — dopiero po zamknięciu
  okna AdMeNot (CloseAppGate). Bez `adb kill-server` — zatrzymałby też serwer adb z Android SDK
  na porcie 5037. StartsWith zamiast -like: [, ] i ` w ścieżce nie są wzorcem, a nazwy procesów
  zawężają filtr, gdyby /DIR= wskazał folder wspólny z innymi programami. }
procedure StopBundleProcesses(AppDir: String);
begin
  PowerShell('Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith('
    + Quoted(AppDir + '\') + ', [StringComparison]::OrdinalIgnoreCase)'
    + ' -and $_.ProcessName -in ''adb'',''scrcpy'',''admenot-cli'' } | Stop-Process -Force');
end;

function AppRunning(AppDir: String): Boolean;
begin
  Result := PowerShell('if (Get-Process AdMeNot -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq '
    + Quoted(AppDir + '\AdMeNot.exe') + ' }) { exit 1 }') = 1;
end;

{ okna nie zabijamy — przerwany zapis dziennika psuje dane do cofania zmian. Z /SUPPRESSMSGBOXES
  domyślna odpowiedź to Anuluj, więc tryb cichy przy uruchomionym programie niczego nie zmienia. }
function CloseAppGate(AppDir: String): Boolean;
begin
  Result := True;
  while Result and AppRunning(AppDir) do
    Result := SuppressibleMsgBox(CustomMessage('CloseApp'), mbError, MB_OKCANCEL, IDCANCEL) = IDOK;
end;

function HasVersion(RootKey: Integer; SubKey: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, SubKey, 'pv', Version)
    and (Version <> '') and (Version <> '0.0.0.0');
end;

function WebView2Installed: Boolean;
begin
  Result := HasVersion(HKLM32, 'SOFTWARE\' + WebView2Key)
    or HasVersion(HKLM64, 'SOFTWARE\' + WebView2Key)
    or HasVersion(HKCU, 'Software\' + WebView2Key);
end;

procedure InstallWebView2;
var
  ResultCode: Integer;
begin
  if WebView2Installed then
    Exit;
  WizardForm.StatusLabel.Caption := CustomMessage('InstallingWebView2');
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  { per-user, bez administratora; wymaga internetu. Niepowodzenie nie przerywa instalacji. }
  Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if not WebView2Installed then
    SuppressibleMsgBox(CustomMessage('WebView2Failed'), mbError, MB_OK, IDOK);
end;

{ Inno woła PrepareToInstall przed sprawdzeniem plików w użyciu (Restart Manager), więc najpierw
  użytkownik zamyka AdMeNot, a dopiero potem zatrzymujemy adb/scrcpy z paczki (spec §6.3).
  Niepusty wynik zatrzymuje instalator na stronie przygotowania, zanim cokolwiek zmieni. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  AppDir: String;
begin
  AppDir := ExpandConstant('{app}');
  if not CloseAppGate(AppDir) then
  begin
    Result := CustomMessage('InstallCancelled');
    Exit;
  end;
  StopBundleProcesses(AppDir);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    InstallWebView2;
end;

function InitializeUninstall: Boolean;
var
  AppDir: String;
begin
  AppDir := ExpandConstant('{app}');
  Result := CloseAppGate(AppDir);
  if Result then
    StopBundleProcesses(AppDir);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { tryb cichy nigdy nie kasuje danych (spec §6.5); domyślny przycisk: Nie }
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox(CustomMessage('DeleteData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\AdMeNot'), True, True, True);
end;
