#define MyAppName "打印农场助手"
#ifndef MyAppVersion
  #define MyAppVersion "1.5.0-beta.1"
#endif
#define MyAppPublisher "Bronove"
#define MyAppExeName "PrintFarmAssistant.exe"

#ifndef SourceDir
  #define SourceDir "..\..\dist_v2\PrintFarmAssistant"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\installer_inno"
#endif

[Setup]
AppId={{BFF95990-77CB-4786-9C88-18A4E56F5654}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/Bronove/printfarm-assistant
AppSupportURL=https://github.com/Bronove/printfarm-assistant/issues
AppUpdatesURL=https://github.com/Bronove/printfarm-assistant/releases
DefaultDirName={localappdata}\Programs\PrintFarmAssistant
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=PrintFarmAssistant-v{#MyAppVersion}-win64-setup
SetupIconFile={#SourceDir}\_internal\icon.ico
UninstallDisplayIcon={app}\_internal\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UsePreviousAppDir=yes
UsePreviousTasks=yes
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll
RestartApplications=no
VersionInfoVersion=1.5.0.1
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion=1.5.0
Uninstallable=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "logs\*,config.json,pet.json,pet.json.e2e,pet.json.probe,usage.json,result.json,*.log"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function FindPreviousInstallDir(): String;
var
  Value: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\拓竹助手V2',
      'InstallLocation', Value) and (Value <> '') then
    Result := Value
  else if RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\拓竹助手',
      'InstallLocation', Value) and (Value <> '') then
    Result := Value
  else if RegQueryStringValue(HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Uninstall\拓竹助手1.0',
      'InstallLocation', Value) and (Value <> '') then
    Result := Value;
end;

function CommandLineHasPrefix(const Prefix: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(Copy(ParamStr(I), 1, Length(Prefix)), Prefix) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

procedure RemovePreviousRegistration();
begin
  RegDeleteKeyIncludingSubkeys(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\拓竹助手V2');
  RegDeleteKeyIncludingSubkeys(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\拓竹助手');
  RegDeleteKeyIncludingSubkeys(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\拓竹助手1.0');
end;

procedure RemovePreviousShortcuts();
var
  Names: array[0..3] of String;
  I: Integer;
begin
  Names := [
    '拓竹助手.lnk',
    '拓竹助手V2.lnk',
    '拓竹助手1.0.lnk',
    '拓竹助手 悬浮助手.lnk'
  ];
  for I := 0 to 3 do
  begin
    DeleteFile(ExpandConstant('{userdesktop}\' + Names[I]));
    DeleteFile(ExpandConstant('{userprograms}\' + Names[I]));
    DeleteFile(ExpandConstant('{userstartup}\' + Names[I]));
  end;
end;

procedure InitializeWizard();
var
  PreviousDir: String;
begin
  try
    PreviousDir := FindPreviousInstallDir();
    if (PreviousDir <> '') and (not CommandLineHasPrefix('/DIR=')) then
      WizardForm.DirEdit.Text := PreviousDir;
  except
    Log('Could not migrate a previous installation directory.');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    try
      RemovePreviousRegistration();
    except
      Log('Could not remove a previous uninstall registration.');
    end;
    try
      RemovePreviousShortcuts();
    except
      Log('Could not remove a previous shortcut.');
    end;
  end;
end;

function WebView2Installed(): Boolean;
begin
  Result :=
    RegKeyExists(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F1E7E1B8-4B2F-4E7C-BADF-9C62C91C986E}') or
    RegKeyExists(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F1E7E1B8-4B2F-4E7C-BADF-9C62C91C986E}') or
    RegKeyExists(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F1E7E1B8-4B2F-4E7C-BADF-9C62C91C986E}');
end;

function BambuStudioInstalled(): Boolean;
var
  Value: String;
begin
  Result :=
    RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\bambu-studio.exe', '', Value) or
    RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\bambu-studio.exe', '', Value) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\App Paths\bambu-studio.exe', '', Value);
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Note: String;
begin
  if CurPageID = wpFinished then
  begin
    try
      Note := '';
      if not WebView2Installed() then
        Note := Note + '未检测到 Microsoft Edge WebView2 Runtime，首次启动前请安装。' + #13#10;
      if not BambuStudioInstalled() then
        Note := Note + '未检测到 Bambu Studio，首次切片前请自行安装。' + #13#10;
      if Note <> '' then
        WizardForm.FinishedLabel.Caption :=
          WizardForm.FinishedLabel.Caption + #13#10 + Note;
    except
      Log('Could not add the optional environment warning.');
    end;
  end;
end;
