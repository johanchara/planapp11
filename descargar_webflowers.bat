@echo off
chcp 65001 >nul
title Descarga WebFlowers - Falcon Farms

REM ── CONFIGURACION ─────────────────────────────────────────────────
set APP_URL=https://planapp11.onrender.com
set ADMIN_USER=admin
set ADMIN_PASS=admin123
set SCRIPT_DIR=%~dp0

REM Fechas: hoy y hace 7 dias
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set dt=%%I
set FECHA_HOY=%dt:~4,2%/%dt:~6,2%/%dt:~0,4%
set /a DIA7=%dt:~6,2%-7
if %DIA7% LEQ 0 set DIA7=01
set FECHA_INICIO=%dt:~4,2%/0%DIA7%/%dt:~0,4%
REM ──────────────────────────────────────────────────────────────────

echo.
echo ============================================================
echo   DESCARGA WEBFLOWERS - FALCON FARMS CALIFORNIA
echo ============================================================
echo.

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado o no esta en PATH.
    echo Instala Python desde https://python.org
    pause
    exit /b 1
)

REM Verificar/instalar dependencias
echo [1/4] Verificando dependencias...
pip show playwright >nul 2>&1
if errorlevel 1 (
    echo Instalando playwright...
    pip install playwright >nul 2>&1
    python -m playwright install chromium >nul 2>&1
)
pip show requests >nul 2>&1
if errorlevel 1 (
    pip install requests >nul 2>&1
)

echo [2/4] Descargando desde WebFlowers...
echo.

REM Correr el script Python
python "%SCRIPT_DIR%webflowers_local.py" "%APP_URL%" "%ADMIN_USER%" "%ADMIN_PASS%"

if errorlevel 1 (
    echo.
    echo [ERROR] La descarga fallo. Revisa los mensajes arriba.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   LISTO - Datos actualizados en la app
echo   Abre: %APP_URL%
echo ============================================================
echo.
pause
