#define AppName "DuyTris Downloader"
#define AppVersion "2.0.5"
#define AppExeName "DuyTrisDownloader.exe"

#ifnexist "..\dist\DuyTrisDownloader\DuyTrisDownloader.exe"
  #error "Missing DuyTrisDownloader.exe. Run build_exe.ps1 first."
#endif
#ifnexist "..\dist\DuyTrisDownloader\ffmpeg.exe"
  #error "Missing ffmpeg.exe. Run build_exe.ps1 first."
#endif
#ifnexist "..\dist\DuyTrisDownloader\ffprobe.exe"
  #error "Missing ffprobe.exe. Run build_exe.ps1 first."
#endif

[Setup]
AppId={{B926E6F8-8064-4BF5-94AE-E5FD59F63287}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=DuyTris
DefaultDirName={localappdata}\Programs\DuyTrisDownloader
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\output
OutputBaseFilename=setup
WizardStyle=modern
DisableWelcomePage=no
DisableDirPage=no
CloseApplications=yes
CloseApplicationsFilter={#AppExeName}
RestartApplications=no
SetupLogging=yes
SetupIconFile=..\img\logo.ico
WizardImageFile=wizard_image.bmp
WizardSmallImageFile=wizard_small.bmp

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\DuyTrisDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.yml"
Source: "..\dist\DuyTrisDownloader\_internal\config.example.yml"; DestName: "config.yml"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
