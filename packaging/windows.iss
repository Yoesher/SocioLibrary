#ifndef AppVersion
#define AppVersion "0.4.0"
#endif
[Setup]
AppId={{9DA31A80-0D44-4490-87B0-8F3B9FA7D6AB}
AppName=SocioLibrary
AppVerName=SocioLibrary
AppVersion={#AppVersion}
AppPublisher=SocioLibrary contributors
AppPublisherURL=https://github.com/Yoesher/SocioLibrary
DefaultDirName={localappdata}\Programs\SocioLibrary
DefaultGroupName=SocioLibrary
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\release-dist
OutputBaseFilename=SocioLibrary-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\SocioLibrary.exe
LicenseFile=..\LICENSE
CloseApplications=yes
RestartApplications=no
AppMutex=SocioLibraryDesktop
UsePreviousAppDir=yes
UsePreviousTasks=yes
DisableDirPage=auto
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "..\dist\SocioLibrary\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\SocioLibrary"; Filename: "{app}\SocioLibrary.exe"; Comment: "SocioLibrary"
Name: "{autodesktop}\SocioLibrary"; Filename: "{app}\SocioLibrary.exe"; Comment: "SocioLibrary"; Tasks: desktopicon
Name: "{autodesktop}\SocioLibrary"; Filename: "{app}\SocioLibrary.exe"; Comment: "SocioLibrary"; Check: ExistingDesktopShortcut
[Run]
Filename: "{app}\SocioLibrary.exe"; Parameters: "--maintenance-clean-runtime"; Flags: runhidden waituntilterminated
Filename: "{app}\SocioLibrary.exe"; Description: "Launch SocioLibrary"; Flags: nowait postinstall skipifsilent
[UninstallDelete]
Type: files; Name: "{app}\bundle-cleanup.json"
; User research data is never deleted by the uninstaller.
[Code]
function ExistingDesktopShortcut(): Boolean;
begin
  Result := FileExists(ExpandConstant('{autodesktop}\SocioLibrary.lnk')) and
            not WizardIsTaskSelected('desktopicon');
end;
