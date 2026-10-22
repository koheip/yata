; GitHub やサイトで配る Setup.exe を作る Inno Setup の設定。
;   iscc /DAppVersion=0.1.0 packaging\windows\yata.iss
; 先に PyInstaller で dist\Yata を作っておくこと。
; 管理者権限なしで、ユーザーのフォルダ（%LOCALAPPDATA%\Programs\Yata）に入れる。

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{8C3F2A61-7B5E-4D2A-9E1C-5A7D3B9F0E42}
AppName=ヤタ
AppVersion={#AppVersion}
AppPublisher=Yata contributors
AppPublisherURL=https://github.com/koheip/yata
DefaultDirName={localappdata}\Programs\Yata
DefaultGroupName=ヤタ
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Yata-Setup-{#AppVersion}
SetupIconFile=yata.ico
UninstallDisplayIcon={app}\Yata.exe
UninstallDisplayName=ヤタ
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにアイコンを作る"; Flags: unchecked

[Files]
Source: "..\..\dist\Yata\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ヤタ"; Filename: "{app}\Yata.exe"
Name: "{autodesktop}\ヤタ"; Filename: "{app}\Yata.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Yata.exe"; Description: "ヤタを起動する"; Flags: nowait postinstall skipifsilent

; アンインストールしても、会話や設定（%LOCALAPPDATA%\Yata）は消さない。
