; Inno Setup script for ZapretDrum.
; Compiles dist\ZapretDrum.exe (built by build_exe.bat) into a normal
; Windows installer: folder picker, Start Menu group, optional desktop
; icon, uninstaller in "Programs and Features".
;
; Requires Inno Setup (free): https://jrsoftware.org/isdl.php

#define MyAppName "ZapretDrum"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0-dev"
#endif
#define MyAppExeName "ZapretDrum.exe"
#define MyAppPublisher "ZapretDrum"

[Setup]
AppId={{A6E1C1B0-5F3E-4B8B-9C2A-3D7E9F1A2B4C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=ZapretDrum-Setup
Compression=lzma2
SolidCompression=yes
; The app needs administrator rights to manage winws.exe/WinDivert,
; so the installer requests the same elevation level.
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\icon.ico

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; shellexec обязателен: у ZapretDrum.exe в манифесте requireAdministrator
; (нужно для управления winws.exe/WinDivert), а обычный CreateProcess не
; умеет запускать такие файлы напрямую - только через ShellExecute, отсюда
; и флаг. Без него после установки будет ошибка "CreateProcess: код 740".
; skipifsilent - галочка "Launch ZapretDrum" нужна только при обычной,
; интерактивной установке. При тихой самообновляющейся установке
; (/VERYSILENT) программу НЕ перезапускаем автоматически: раньше здесь
; были попытки автоперезапуска с ретраями, но выяснилось, что если запуск
; падает из-за антивируса/проверки репутации SmartScreen, каждая неудачная
; попытка показывает своё собственное пугающее системное окно "Failed to
; load Python DLL" (это делает сам бутлоадер PyInstaller изнутри упавшего
; процесса - подавить это окно нельзя). Поэтому просто ничего не
; перезапускаем: само приложение (core/app_updater.py + ui/main_window.py)
; перед закрытием честно предупреждает пользователя, что после установки
; нужно открыть ZapretDrum вручную - надёжнее, чем гадать, сработает ли
; автозапуск.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall shellexec skipifsilent

[Code]
// Полная деинсталляция: помимо файлов, которые ставил сам инсталлятор
// (это Inno Setup делает автоматически), нужно ещё:
//  1. остановить и удалить службу Windows "zapret" / "WinDivert", если она
//     была установлена через кнопку "Установить как службу" в приложении;
//  2. на всякий случай убить процесс winws.exe, если он ещё запущен;
//  3. спросить пользователя, удалять ли скачанный zapret и настройки
//     приложения в %LOCALAPPDATA%\ZapretDrum (эту папку создал не
//     инсталлятор, а само приложение при первом запуске, поэтому
//     Inno Setup не знает о ней и не удалит её сам).
procedure RemoveOwnedService(Name, DataDir: String);
var
  ImagePath: String;
  ResultCode: Integer;
begin
  if RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Services\' + Name, 'ImagePath', ImagePath) then
  begin
    ImagePath := Lowercase(ImagePath);
    if (Pos('"' + Lowercase(DataDir) + '\zapret\', ImagePath) = 1) or
       (Pos(Lowercase(DataDir) + '\zapret\', ImagePath) = 1) or
       (Pos('\??\' + Lowercase(DataDir) + '\zapret\', ImagePath) = 1) then
    begin
      Exec(ExpandConstant('{sys}\sc.exe'), 'stop ' + Name, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Exec(ExpandConstant('{sys}\sc.exe'), 'delete ' + Name, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  DataDir: String;
  EscapedDir: String;
begin
  DataDir := ExpandConstant('{localappdata}\ZapretDrum');
  if CurUninstallStep = usUninstall then
  begin
    RemoveOwnedService('zapret', DataDir);
    RemoveOwnedService('WinDivert', DataDir);
    RemoveOwnedService('WinDivert14', DataDir);
    EscapedDir := DataDir;
    StringChangeEx(EscapedDir, '''', '''''', True);
    Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -WindowStyle Hidden -Command "Get-Process -Name winws,TgWsProxy_windows -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq ''' + EscapedDir + '\zapret\bin\winws.exe'' -or $_.Path -eq ''' + EscapedDir + '\tg-ws-proxy\TgWsProxy_windows.exe'' } | Stop-Process -Force"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    if DirExists(DataDir) then
    begin
      if MsgBox('Также удалить скачанные zapret, tg-ws-proxy и их настройки?' + #13#10 + DataDir,
        mbConfirmation, MB_YESNO) = IDYES then
      begin
        DeleteFile(ExpandConstant('{userstartup}\ZapretDrum-TgWsProxy.lnk'));
        DeleteFile(ExpandConstant('{userstartup}\ZapretDrum-TgWsProxy.vbs'));
        if not DelTree(DataDir, True, True, True) then
          MsgBox('Часть файлов ещё занята. После перезагрузки их можно удалить из папки:' + #13#10 + DataDir, mbInformation, MB_OK);
      end;
    end;
  end;
end;
