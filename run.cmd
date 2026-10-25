@echo off
setlocal
rem Claudefire launcher: installs uv if needed, then runs the fire demo.
rem With no arguments it runs fullscreen windowed (--borderless); any arguments
rem are passed straight through, e.g.  run.cmd --windowed --size 2560x1440

pushd "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    rem uv may already be installed but not yet on PATH in this console.
    if exist "%USERPROFILE%\.local\bin\uv.exe" (
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    ) else (
        echo uv not found - installing it from astral.sh ...
        powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        if errorlevel 1 (
            echo Failed to install uv.
            popd
            pause
            exit /b 1
        )
        set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    )
)

if "%~1"=="" (
    uv run claudefire --borderless
) else (
    uv run claudefire %*
)
set "RC=%ERRORLEVEL%"

popd
if not "%RC%"=="0" pause
exit /b %RC%
