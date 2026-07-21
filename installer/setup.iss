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
; skipifsilent - эта галочка "Launch ZapretDrum" нужна только при обычной,
; интерактивной установке. Тихую самообновляющуюся установку (/VERYSILENT)
; она тоже могла бы запустить, но без права на повторную попытку - если
; в этот момент антивирус ещё сканирует свежеустановленный exe, запуск
; падает с ошибкой вида "Failed to load Python DLL" и человеку приходится
; открывать программу вручную. Поэтому для тихого запуска ниже есть
; отдельная логика в CurStepChanged - с паузой и повторными попытками.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall shellexec skipifsilent

[Code]
// Перезапуск ZapretDrum после ТИХОЙ установки (самообновление из самого
// приложения, core.app_updater.download_and_launch_update -> /VERYSILENT).
// Проблема, которую это чинит: если запустить свежеустановленный exe
// сразу же, антивирус (чаще всего встроенный Защитник Windows) иногда
// ещё сканирует его в этот самый момент, и PyInstaller-бутлоадер не может
// распаковать/загрузить свою DLL ("Failed to load Python DLL ... LoadLibrary:
// не найден указанный модуль") - хотя сам файл на диске совершенно цел
// (что и подтвердилось: повторный запуск вручную через минуту сработал).
// Решение - не полагаться на единственную попытку сразу: подождать и,
// если не получилось, попробовать ещё раз (с увеличивающейся паузой).
procedure LaunchAfterSilentUpdate();
var
  ResultCode: Integer;
  Attempt: Integer;
  Launched: Boolean;
begin
  Launched := False;
  for Attempt := 1 to 4 do
  begin
    Sleep(1000 * Attempt);  // 1с, 2с, 3с, 4с - даём антивирусу "остыть"
    if ShellExec('open', ExpandConstant('{app}\{#MyAppExeName}'), '', '',
      SW_SHOWNORMAL, ewNoWait, ResultCode) then
    begin
      Launched := True;
      Break;
    end;
  end;
  // Если все попытки не удались - молча сдаёмся: пользователь всё равно
  // увидит, что ZapretDrum не открылся, и запустит его сам через ярлык
  // (сама установка при этом прошла успешно, файлы на месте).
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssDone) and WizardSilent() then
    LaunchAfterSilentUpdate();
end;

// Полная деинсталляция: помимо файлов, которые ставил сам инсталлятор
// (это Inno Setup делает автоматически), нужно ещё:
//  1. остановить и удалить службу Windows "zapret" / "WinDivert", если она
//     была установлена через кнопку "Установить как службу" в приложении;
//  2. на всякий случай убить процесс winws.exe, если он ещё запущен;
//  3. спросить пользователя, удалять ли скачанный zapret и настройки
//     приложения в %LOCALAPPDATA%\ZapretDrum (эту папку создал не
//     инсталлятор, а само приложение при первом запуске, поэтому
//     Inno Setup не знает о ней и не удалит её сам).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    Exec('cmd.exe', '/c net stop zapret & sc delete zapret & net stop WinDivert & sc delete WinDivert & net stop WinDivert14 & sc delete WinDivert14',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM winws.exe /F', '',
      SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\ZapretDrum');
    if DirExists(DataDir) then
    begin
      if MsgBox('Также удалить скачанный zapret и настройки приложения?' + #13#10 + DataDir,
        mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
