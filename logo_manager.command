#!/usr/bin/env bash
# Gestor web de logos - lanzador para macOS (doble clic).
# Verifica Python, prepara un entorno virtual, instala lo que falte y abre la app.
# Uso:  ./logo_manager.command [--port 5050] [--no-browser]

set -u
cd "$(dirname "$0")" || exit 1

pause_on_error() {
  echo
  read -r -p "Pulsa Enter para cerrar..." _
  exit 1
}

# --- 1. Localizar Python ----------------------------------------------------
SYSTEM_PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    SYSTEM_PY="$candidate"
    break
  fi
done

if [ -z "$SYSTEM_PY" ]; then
  echo "[ERROR] No se encontro Python 3.9 o superior."
  echo "        Instalalo desde https://www.python.org/downloads/ o con: brew install python"
  pause_on_error
fi

# --- 2. Entorno virtual (evita problemas de permisos de pip) -----------------
VENV_DIR=".venv"
if [ -x "$VENV_DIR/bin/python" ]; then
  PY="$VENV_DIR/bin/python"
else
  echo "Creando entorno virtual en $VENV_DIR..."
  if ! "$SYSTEM_PY" -m venv "$VENV_DIR"; then
    echo "[ERROR] No se pudo crear el entorno virtual."
    pause_on_error
  fi
  PY="$VENV_DIR/bin/python"
  "$PY" -m pip install --disable-pip-version-check --quiet --upgrade pip >/dev/null 2>&1 || true
fi

# --- 3. Dependencias del gestor (Flask + Pillow + requests) -----------------
if ! "$PY" -c 'import flask, PIL, requests' >/dev/null 2>&1; then
  echo "Instalando dependencias del gestor [Flask, Pillow, requests]..."
  if ! "$PY" -m pip install --disable-pip-version-check --quiet \
      "Flask>=3.0" "Pillow>=11.0" "requests>=2.32.0"; then
    echo "[ERROR] No se pudieron instalar las dependencias."
    echo "        Prueba manualmente:  $PY -m pip install -r requirements.txt"
    pause_on_error
  fi
fi

# --- 4. Backend para logos SVG (opcional) -----------------------------------
if ! "$PY" -c 'import cairosvg' >/dev/null 2>&1 &&
   ! "$PY" -c 'import resvg_py' >/dev/null 2>&1; then
  echo "Instalando soporte para logos SVG [resvg-py]..."
  "$PY" -m pip install --disable-pip-version-check --quiet "resvg-py>=0.5.0" >/dev/null 2>&1 ||
    echo "[AVISO] Sin soporte para SVG; los PNG, JPG, WEBP y GIF funcionan igual."
fi

# --- 5. Lanzar la aplicacion ------------------------------------------------
echo "Iniciando el gestor de logos..."
echo "Pulsa Ctrl+C para detenerlo."
echo
"$PY" tools/logo_manager/app.py "$@"
status=$?

if [ "$status" -ne 0 ]; then
  echo
  echo "El gestor se cerro con un error. Revisa el mensaje anterior."
  echo "Si el puerto esta ocupado, prueba:  ./logo_manager.command --port 5050"
  pause_on_error
fi
