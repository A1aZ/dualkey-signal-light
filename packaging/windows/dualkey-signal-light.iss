#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif

[Setup]
AppId={{94E9A4E5-F922-4E8F-9575-7832D4EF98EF}
AppName=DualKey Signal Light
AppVersion={#AppVersion}
AppVerName=DualKey Signal Light {#AppVersion}
AppPublisher=A1aZ and DualKey Signal Light contributors
AppPublisherURL=https://github.com/A1aZ/dualkey-signal-light
AppSupportURL=https://github.com/A1aZ/dualkey-signal-light/issues
AppUpdatesURL=https://github.com/A1aZ/dualkey-signal-light/releases
DefaultDirName={localappdata}\Programs\DualKey Signal Light
DefaultGroupName=DualKey Signal Light
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\build\installers
OutputBaseFilename=dualkey-signal-light-{#AppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\..\LICENSE
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=DualKey Signal Light

[Files]
Source: "..\..\build\package\dualkey-light\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autostartup}\DualKey Signal Light"; Filename: "{app}\dualkey-light-service.exe"; Parameters: "serve --transport auto --install-integrations"; WorkingDir: "{app}"
Name: "{group}\Uninstall DualKey Signal Light"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\dualkey-light.exe"; Parameters: "install-integrations --agents auto"; Description: "Detecting installed coding agents"; StatusMsg: "Installing Agent integrations..."; Flags: runhidden waituntilterminated
Filename: "{app}\dualkey-light-service.exe"; Parameters: "serve --transport auto --install-integrations"; Description: "Start DualKey Signal Light"; Flags: nowait postinstall skipifsilent runhidden

[UninstallRun]
Filename: "{app}\dualkey-light.exe"; Parameters: "shutdown"; Flags: runhidden waituntilterminated; RunOnceId: "StopBridge"
Filename: "{app}\dualkey-light.exe"; Parameters: "uninstall-integrations --agents all"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveIntegrations"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssInstall) and FileExists(ExpandConstant('{app}\dualkey-light.exe')) then
  begin
    Exec(
      ExpandConstant('{app}\dualkey-light.exe'),
      'shutdown',
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    );
    Sleep(500);
  end;
end;
