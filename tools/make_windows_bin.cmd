@echo off
setlocal

set "ROOT=%~dp0.."
pushd "%ROOT%" >nul

set "ONEFILE=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--onefile" (
    set "ONEFILE=1"
    shift
    goto parse_args
)
if /I "%~1"=="-h" goto usage
if /I "%~1"=="--help" goto usage
echo Unknown option: %~1
goto usage_error

:args_done
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    set "PYTHON=python"
)

"%PYTHON%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed in this environment.
    echo Install it with:
    echo   "%PYTHON%" -m pip install pyinstaller
    popd >nul
    exit /b 1
)

if "%ONEFILE%"=="1" (
    set "OPTILAND_ONEFILE=1"
    echo Building Optiland as a single-file executable...
) else (
    set "OPTILAND_ONEFILE=0"
    echo Building Optiland as a one-folder executable...
)

tasklist /FI "IMAGENAME eq Optiland.exe" 2>nul | find /I "Optiland.exe" >nul
if not errorlevel 1 (
    echo Optiland.exe is still running.
    echo Close the application before rebuilding, then run this command again.
    popd >nul
    exit /b 1
)

"%PYTHON%" -m PyInstaller --noconfirm --clean optiland.spec
if errorlevel 1 (
    popd >nul
    exit /b 1
)

if "%ONEFILE%"=="1" (
    echo.
    echo Build complete: dist\Optiland.exe
) else (
    echo.
    echo Build complete: dist\Optiland\Optiland.exe
)

popd >nul
exit /b 0

:usage
echo Usage:
echo   tools\make_windows_bin.cmd [--onefile]
echo.
echo Default builds dist\Optiland\Optiland.exe.
echo --onefile builds dist\Optiland.exe.
popd >nul
exit /b 0

:usage_error
echo.
echo Usage:
echo   tools\make_windows_bin.cmd [--onefile]
popd >nul
exit /b 2
