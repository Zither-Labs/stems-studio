; Stems Studio - Windows Setup Installer (Inno Setup 6)
; Built automatically by GitHub Actions (tools/build_release_assets.py) into dist/StemsStudio-Setup.exe

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8E4A2F9C-5B71-4D3A-9F1E-6C8D2A4B7E10}
AppName=Stems Studio
AppVersion={#AppVersion}
AppPublisher=Bikash Acharya
AppPublisherURL=https://github.com/Zither-Labs/stems-studio
AppSupportURL=https://github.com/Zither-Labs/stems-studio/releases
DefaultDirName={autopf}\StemsStudio
DefaultGroupName=Stems Studio
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=StemsStudio-Setup
SetupIconFile=..\assets\install.ico
UninstallDisplayIcon={app}\assets\stems-studio.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\updater.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\version.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\index.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\manifest.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\favicon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Install.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Update.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Install.command"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\INSTALL.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\css\*"; DestDir: "{app}\css"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\fonts\*"; DestDir: "{app}\fonts"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\js\*"; DestDir: "{app}\js"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\separator\*"; DestDir: "{app}\separator"; Excludes: "__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\tools\*"; DestDir: "{app}\tools"; Excludes: "__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Stems Studio Setup"; Filename: "{app}\Install.bat"; WorkingDir: "{app}"; IconFilename: "{app}\assets\install.ico"
Name: "{autoprograms}\Update Stems Studio"; Filename: "{app}\Update.bat"; WorkingDir: "{app}"; IconFilename: "{app}\assets\install.ico"

[Run]
Filename: "{app}\Install.bat"; WorkingDir: "{app}"; Description: "Complete first-time environment setup (Python 3.12, AI stem models, and Desktop shortcuts)"; Flags: postinstall shellexec waituntilterminated

