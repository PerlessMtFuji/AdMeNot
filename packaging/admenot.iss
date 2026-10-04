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
pl.DeleteData=Usunąć też dane AdMeNot (dziennik zleceń, kopie, protokoły, zrzuty, pamięć podręczna APK)?%n%nDziennik jest potrzebny, żeby cofnąć zmiany na telefonach klientów.
en.DeleteData=Also delete AdMeNot data (job journal, backups, reports, screenshots, APK cache)?%n%nThe journal is needed to undo changes on customers' phones.
pl.CloseApp=AdMeNot jest uruchomiony. Zamknij program i kliknij OK.
en.CloseApp=AdMeNot is running. Close the program and click OK.
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

{ Spec §6.3: adb kill-server, potem procesy z katalogu programu. adb z innych miejsc zostaje.
  KeepApp: przy instalacji AdMeNot.exe zamyka Restart Manager (CloseApplications=force). }
procedure StopBundleProcesses(AppDir: String; KeepApp: Boolean);
var
  ResultCode: Integer;
  Adb, Filter: String;
begin
  Adb := AppDir + '\_internal\admenot\assets\tools\scrcpy\adb.exe';
  if FileExists(Adb) then
    Exec(Adb, 'kill-server', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Filter := '$_.Path -like ' + Quoted(AppDir + '\*');
  if KeepApp then
    Filter := Filter + ' -and $_.ProcessName -ne ''AdMeNot''';
  PowerShell('Get-Process | Where-Object { ' + Filter + ' } | Stop-Process -Force');
end;

function AppRunning(AppDir: String): Boolean;
begin
  Result := PowerShell('if (Get-Process AdMeNot -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq '
    + Quoted(AppDir + '\AdMeNot.exe') + ' }) { exit 1 }') = 1;
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

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopBundleProcesses(ExpandConstant('{app}'), True);
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
  Result := True;
  { okna nie zabijamy — przerwany zapis dziennika psuje dane do cofania zmian }
  while Result and AppRunning(AppDir) do
    Result := SuppressibleMsgBox(CustomMessage('CloseApp'), mbError, MB_OKCANCEL, IDCANCEL) = IDOK;
  if Result then
    StopBundleProcesses(AppDir, False);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { tryb cichy nigdy nie kasuje danych (spec §6.5); domyślny przycisk: Nie }
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox(CustomMessage('DeleteData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\AdMeNot'), True, True, True);
end;
