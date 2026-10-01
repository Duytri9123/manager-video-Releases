#define AppVersion "2.0.6"
#ifdef CustomerBuild
#define AppName "DuyTris Customer"
#define AppExeName "DuyTrisCustomer.exe"
#define DistDir "..\dist\DuyTrisCustomer"
#define SetupName "DuyTrisCustomer_Setup"
#else
#define AppName "DuyTris Downloader"
#define AppExeName "DuyTrisDownloader.exe"
#define DistDir "..\dist\DuyTrisDownloader"
#define SetupName "setup"
#endif

#ifnexist DistDir + "\" + AppExeName
  #error "Missing DuyTrisDownloader.exe. Run build_exe.ps1 first."
#endif
#ifnexist DistDir + "\ffmpeg.exe"
  #error "Missing ffmpeg.exe. Run build_exe.ps1 first."
#endif
#ifnexist DistDir + "\ffprobe.exe"
  #error "Missing ffprobe.exe. Run build_exe.ps1 first."
#endif

[Setup]
#ifdef CustomerBuild
AppId={{07123A26-A546-467C-83DF-9083FBB5E5BE}
#else
AppId={{B926E6F8-8064-4BF5-94AE-E5FD59F63287}
#endif
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=DuyTris
#ifdef CustomerBuild
DefaultDirName={localappdata}\Programs\DuyTrisCustomer
#else
DefaultDirName={localappdata}\Programs\DuyTrisDownloader
#endif
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
OutputBaseFilename={#SetupName}
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

[InstallDelete]
; Older builds bundled Poppler's incompatible ICU DLL. Inno Setup keeps files
; removed from newer builds unless they are explicitly deleted on upgrade.
Type: files; Name: "{app}\icuuc.dll"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.yml,*.db,.state\*,.accounts\*,.youtube_tokens\*"
Source: "{#DistDir}\config.example.yml"; DestName: "config.yml"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\DuyTris System Hub"; Filename: "{app}\BẬT_TẮT_HỆ_THỐNG_UI.bat"; WorkingDir: "{app}"
Name: "{userdesktop}\DuyTris System Hub"; Filename: "{app}\BẬT_TẮT_HỆ_THỐNG_UI.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; ValueType: string; ValueName: "Path"; ValueData: "{app}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
