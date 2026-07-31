#define MyAppName "Vimoose"
#define MyAppVersion "0.7.0"
#define MyAppPublisher "KIdiens"
#define MyAppURL "https://github.com/KIdiens/Vimoose"
#define MyAppExeName "Vimoose.exe"

[Setup]
; 沿用旧版AppId，让GesturePilot用户可直接升级到Vimoose。
AppId={{8AFEA572-7591-4F45-B5DB-1F71C5E62C84}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=Vimoose-{#MyAppVersion}-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："; Flags: unchecked
Name: "startup"; Description: "登录 Windows 后自动启动"; GroupDescription: "附加选项："; Flags: unchecked

[Files]
Source: "..\dist\Vimoose\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Vimoose"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Vimoose"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "GesturePilot"; Flags: deletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Vimoose"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 Vimoose"; Flags: nowait postinstall skipifsilent
