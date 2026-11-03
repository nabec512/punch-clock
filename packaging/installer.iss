; Per-user installer: no admin rights needed. Built by packaging\build.ps1,
; which passes the version as /DAppVersion=x.y.z.
#ifndef AppVersion
  #error Run through packaging\build.ps1, or pass /DAppVersion=x.y.z
#endif

[Setup]
; Keep this AppId unchanged across releases so new versions upgrade in place.
AppId={{84A244EC-00FB-4D9D-B075-4AA12B0EA799}
AppName=Punch Clock
AppVersion={#AppVersion}
DefaultDirName={autopf}\Punch Clock
DefaultGroupName=Punch Clock
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=PunchClock-{#AppVersion}-setup
UninstallDisplayIcon={app}\PunchClock.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\PunchClock\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Punch Clock"; Filename: "{app}\PunchClock.exe"
Name: "{autodesktop}\Punch Clock"; Filename: "{app}\PunchClock.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PunchClock.exe"; Description: "Start Punch Clock"; Flags: nowait postinstall skipifsilent
; After the app updates itself, the silent install reopens it.
Filename: "{app}\PunchClock.exe"; Flags: nowait; Check: ReopenAfterUpdate

[Code]
function ReopenAfterUpdate: Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:reopen|0}') = '1');
end;
