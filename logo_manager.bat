@echo off
rem Gestor web de logos - solucion de un clic.
rem Verifica Python, instala las dependencias que falten y abre la aplicacion.
rem Uso:  logo_manager.bat [--port 5050] [--no-browser]
setlocal EnableExtensions
title Gestor de logos
cd /d "%~dp0"

rem --- 1. Localizar Python -------------------------------------------------
set "PY="
where python >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY (
  where py >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  echo [ERROR] No se encontro Python en el PATH.
  echo         Instala Python 3.9 o superior desde https://www.python.org/downloads/
  echo         y marca la opcion "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Se requiere Python 3.9 o superior. Version detectada:
  %PY% --version
  echo.
  pause
  exit /b 1
)

rem --- 2. Dependencias del gestor (Flask + Pillow + requests) --------------
%PY% -c "import flask, PIL, requests" >nul 2>&1
if errorlevel 1 call :install_deps
if errorlevel 1 exit /b 1

rem --- 2b. Backend para logos SVG (opcional) -------------------------------
call :svg_support

rem --- 3. Lanzar la aplicacion --------------------------------------------
echo Iniciando el gestor de logos...
echo Pulsa Ctrl+C para detenerlo.
echo.
%PY% tools\logo_manager\app.py %*
if errorlevel 1 (
  echo.
  echo El gestor se cerro con un error. Revisa el mensaje anterior.
  echo Si el puerto esta ocupado, prueba:  logo_manager.bat --port 5050
  echo.
  pause
)

endlocal
exit /b 0

rem ---------------------------------------------------------------------------
:install_deps
echo Instalando dependencias del gestor [Flask, Pillow, requests]...
%PY% -m pip install --disable-pip-version-check --quiet "Flask>=3.0" "Pillow>=11.0" "requests>=2.32.0"
if not errorlevel 1 exit /b 0
echo Reintentando la instalacion para el usuario actual...
%PY% -m pip install --disable-pip-version-check --quiet --user "Flask>=3.0" "Pillow>=11.0" "requests>=2.32.0"
if errorlevel 1 (
  echo.
  echo [ERROR] No se pudieron instalar Flask, Pillow y requests.
  echo         Ejecuta manualmente:
  echo             %PY% -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)
exit /b 0

rem ---------------------------------------------------------------------------
:svg_support
rem cairosvg necesita la libreria nativa Cairo (poco comun en Windows);
rem resvg-py es un wheel autonomo que funciona en todas las plataformas.
%PY% -c "import cairosvg" >nul 2>&1
if not errorlevel 1 exit /b 0
%PY% -c "import resvg_py" >nul 2>&1
if not errorlevel 1 exit /b 0
echo Instalando soporte para logos SVG [resvg-py]...
%PY% -m pip install --disable-pip-version-check --quiet "resvg-py>=0.5.0" >nul 2>&1
if errorlevel 1 (
  echo [AVISO] No se pudo instalar el soporte para SVG.
  echo         Los logos PNG, JPG, WEBP y GIF funcionan igualmente.
  echo.
)
exit /b 0
