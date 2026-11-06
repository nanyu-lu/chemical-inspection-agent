; Inno Setup 打包脚本（Windows）
; 需要先执行：pyinstaller packaging\chem.spec  → build\dist\ChemInspect\
; 产物：dist\chem-inspect-Setup-<版本>.exe

#define MyAppName "化工巡检"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Scouter"
#define MyAppExeName "ChemInspect.exe"

[Setup]
AppId={{8B4E1B3E-2C77-4E31-9F1E-6A1B2C3D4E5F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=chem-inspect-Setup-{#MyAppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 不需要管理员权限：装到当前用户目录
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
; Inno Setup 不内置简体中文，CI 会尝试下载；拿不到就自动回落英文，保证一定能编译
Name: "english"; MessagesFile: "compiler:Default.isl"
#if FileExists("C:\Program Files (x86)\Inno Setup 6\Languages\ChineseSimplified.isl")
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "..\build\dist\ChemInspect\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\首次打开说明"; Filename: "{app}\首次打开说明.txt"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\首次打开说明.txt"; Description: "查看首次打开说明"; Flags: shellexec nowait postinstall skipifsilent unchecked
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
