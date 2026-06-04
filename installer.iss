; Inno Setup script for JustATuner (Windows).
; Wraps the PyInstaller-built dist\JustATuner.exe into an installer that
; places the app under Program Files, adds Start Menu / optional desktop
; shortcuts, and registers an uninstaller.
;
; Build locally (after `python build.py`):
;   iscc /DAppVersion=1.0.0 installer.iss
;
; CI passes /DAppVersion automatically from config.py's APP_VERSION.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "JustATuner"
#define AppPublisher "Matt Stohrer"
#define AppURL "https://www.stohrermusic.com"
#define AppExeName "JustATuner.exe"

[Setup]
; Stable product GUID — DO NOT change between releases, or Windows will
; treat upgrades as a different product and leave the old install behind.
AppId={{515F5C95-7DF0-4822-81C3-1C4BD85AF074}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppCopyright=Copyright (C) Matt Stohrer
DefaultDirName={autopf}\JustATuner
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=JustATuner-Windows-Setup-{#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
; Require Windows 10 or newer (Python 3.11 / PyInstaller drop support below this).
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\JustATuner.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
