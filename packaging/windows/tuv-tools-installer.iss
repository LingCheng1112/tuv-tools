#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

#define AppId "{{D1D785F8-44A7-492D-B8CF-22931D220DCF}"
#define AppName "TUV项目文档工具"
#define AppPublisher "TUV Tools"
#define AppExeName "TUV项目文档工具.exe"
#define AppDirName "TUV-Project-Document-Tool"
#define DistDir "..\..\dist\TUV-Project-Document-Tool"
#define OutputDir "..\..\dist\installer"
#define SetupIcon "..\..\resources\favicon.ico"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppDirName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=tuv-tools-setup-{#AppVersion}
SetupIconFile={#SetupIcon}
UninstallDisplayIcon={app}\{#AppExeName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UsedUserAreasWarning=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Excludes: ".tuv-tools\*;doc_output\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\.tuv-tools-config.json"

[Code]
function EscapeJsonString(const Value: string): string;
begin
  Result := Value;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
end;

function GetBootstrapPath: string;
begin
  Result := ExpandConstant('{app}\.tuv-tools-config.json');
end;

function GetDefaultDataRoot: string;
begin
  Result := ExpandConstant('{localappdata}\{#AppDirName}\.tuv-tools');
end;

function GetDefaultOutputRoot: string;
begin
  Result := ExpandConstant('{userdocs}\{#AppDirName}\doc_output');
end;

procedure EnsureBootstrapConfig;
var
  BootstrapPath: string;
  DataRoot: string;
  OutputRoot: string;
  BootstrapJson: string;
begin
  BootstrapPath := GetBootstrapPath();
  if FileExists(BootstrapPath) then
    exit;

  DataRoot := GetDefaultDataRoot();
  OutputRoot := GetDefaultOutputRoot();
  ForceDirectories(DataRoot);
  ForceDirectories(OutputRoot);

  BootstrapJson :=
    '{' + #13#10 +
    '  "appDataRoot": "' + EscapeJsonString(DataRoot) + '",' + #13#10 +
    '  "splitterOutputRoot": "' + EscapeJsonString(OutputRoot) + '"' + #13#10 +
    '}';
  SaveStringToFile(BootstrapPath, BootstrapJson, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    EnsureBootstrapConfig();
end;
