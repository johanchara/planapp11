"""
webflowers_local.py
Descarga el Sales Report de WebFlowers y lo sube a la app en Render.
Uso: python webflowers_local.py <APP_URL> <USUARIO> <PASSWORD>
"""
import sys
import os
import tempfile
import time
import requests
from datetime import datetime, timedelta

# ── CONFIG ─────────────────────────────────────────────────────────
APP_URL      = sys.argv[1] if len(sys.argv) > 1 else "https://planapp11.onrender.com"
ADMIN_USER   = sys.argv[2] if len(sys.argv) > 2 else "admin"
ADMIN_PASS   = sys.argv[3] if len(sys.argv) > 3 else "admin123"

WF_URL  = os.environ.get("WEBFLOWERS_URL",  "http://webflowersffcalifornia.azurewebsites.net/Default_new.aspx")
WF_USER = os.environ.get("WEBFLOWERS_USER", "Jchara")
WF_PASS = os.environ.get("WEBFLOWERS_PASS", "Bruno2018!")

fecha_fin    = datetime.today()
fecha_inicio = fecha_fin - timedelta(days=7)
DATE_FROM = fecha_inicio.strftime("%m/%d/%Y")
DATE_TO   = fecha_fin.strftime("%m/%d/%Y")
# ───────────────────────────────────────────────────────────────────


def log(msg):
    print(f"  {msg}", flush=True)


def login_app():
    """Obtiene token JWT de la app."""
    log(f"Conectando a {APP_URL}...")
    # La app puede estar dormida en Render Free - esperar hasta 60s
    for intento in range(4):
        try:
            r = requests.post(
                f"{APP_URL}/api/auth/login",
                json={"username": ADMIN_USER, "password": ADMIN_PASS},
                timeout=30
            )
            if r.status_code == 200:
                token = r.json().get("access_token")
                log("Login en la app exitoso")
                return token
            else:
                log(f"Error login: {r.status_code} - {r.text[:100]}")
                return None
        except requests.exceptions.ConnectionError:
            if intento < 3:
                log(f"App dormida, esperando 20s... (intento {intento+1}/4)")
                time.sleep(20)
            else:
                log("No se pudo conectar a la app")
                return None


def download_webflowers():
    """Descarga el Sales Report usando Playwright."""
    from playwright.sync_api import sync_playwright

    log(f"Iniciando Chromium...")
    download_dir = tempfile.mkdtemp(prefix="webflowers_")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        page.set_default_timeout(30000)

        try:
            log(f"Conectando a WebFlowers...")
            page.goto(WF_URL, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            log("Iniciando sesion en WebFlowers...")
            page.locator("input[placeholder*='User']").fill(WF_USER)
            page.locator("input[type='password']").fill(WF_PASS)
            page.locator("input[value='Sign In']").click()
            time.sleep(6)
            log("Sesion iniciada")

            base_url = "/".join(page.url.split("/")[:-1])
            sales_url = (
                f"{base_url}/Reports/Sales/SalesReport.aspx"
                f"?xapApplicationName=&menuId=REPORTS_SALES_3&caption=Sales+Table"
            )

            main_frame = page.frame(name="main")
            if not main_frame:
                for f in page.frames:
                    if "SalesReport" in f.url or f.name == "main":
                        main_frame = f
                        break
            if not main_frame:
                main_frame = page.frames[2] if len(page.frames) > 2 else page.main_frame

            log("Navegando a Sales Table...")
            main_frame.goto(sales_url, wait_until="domcontentloaded")
            time.sleep(4)

            frame = page.frame(name="main")
            if not frame:
                for f in page.frames:
                    if "SalesReport" in f.url:
                        frame = f
                        break
            if not frame:
                frame = page.frames[2] if len(page.frames) > 2 else page.main_frame

            log("Configurando filtros...")
            frame.evaluate("""
                var selects = document.querySelectorAll('select');
                for(var i=0;i<selects.length;i++){
                    for(var j=0;j<selects[i].options.length;j++){
                        if(selects[i].options[j].text.trim()==='[All]'){
                            selects[i].selectedIndex = j;
                            selects[i].dispatchEvent(new Event('change'));
                            break;
                        }
                    }
                }
            """)
            time.sleep(1)

            frame.evaluate("""
                var selects = document.querySelectorAll('select');
                for(var i=0;i<selects.length;i++){
                    for(var j=0;j<selects[i].options.length;j++){
                        if(selects[i].options[j].text.trim()==='Single-Store'){
                            selects[i].selectedIndex = j;
                            selects[i].dispatchEvent(new Event('change'));
                            break;
                        }
                    }
                }
            """)
            time.sleep(1)

            log(f"Fechas: {DATE_FROM} → {DATE_TO}")
            frame.evaluate(f"""
                var from = document.getElementById('txtDateFrom');
                from.value = '{DATE_FROM}';
                from.dispatchEvent(new Event('change'));
                var to = document.getElementById('txtDateTo');
                to.value = '{DATE_TO}';
                to.dispatchEvent(new Event('change'));
            """)
            time.sleep(0.5)

            log("Cargando datos (espere ~8 segundos)...")
            frame.evaluate("""
                var btns = document.querySelectorAll('input[type="button"],button');
                for(var i=0;i<btns.length;i++){
                    if(btns[i].value==='Refresh' || btns[i].innerText==='Refresh'){
                        btns[i].click();
                        break;
                    }
                }
            """)
            time.sleep(8)

            log("Descargando archivo Excel...")
            frame = page.frame(name="main")
            if not frame:
                for f in page.frames:
                    if "SalesReport" in f.url:
                        frame = f
                        break
            if not frame:
                frame = page.frames[2] if len(page.frames) > 2 else page.main_frame

            with page.expect_download(timeout=60000) as dl:
                frame.locator("input[type='image'][id='btnConvertToExcel']").click()

            download = dl.value
            filename = download.suggested_filename or "SalesReport.xls"
            dest = os.path.join(download_dir, filename)
            download.save_as(dest)
            log(f"Archivo descargado: {filename}")
            return dest

        finally:
            browser.close()


def upload_to_app(filepath, token):
    """Sube el archivo a la app en Render."""
    log("Subiendo datos a la app...")
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        r = requests.post(
            f"{APP_URL}/api/import/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (filename, f, "application/octet-stream")},
            timeout=120
        )
    if r.status_code == 200:
        result = r.json().get("result", {})
        insertados = result.get("insertados", "?")
        log(f"✓ {insertados} registros importados correctamente")
        return True
    else:
        log(f"Error al subir: {r.status_code} - {r.text[:200]}")
        return False


if __name__ == "__main__":
    print()
    print(f"  Periodo: {DATE_FROM} → {DATE_TO}")
    print()

    # 1. Login en la app
    token = login_app()
    if not token:
        print("\n[ERROR] No se pudo autenticar en la app")
        sys.exit(1)

    # 2. Descargar WebFlowers
    try:
        filepath = download_webflowers()
    except Exception as e:
        print(f"\n[ERROR] Fallo la descarga de WebFlowers: {e}")
        sys.exit(1)

    # 3. Subir a la app
    ok = upload_to_app(filepath, token)

    # Limpiar archivo temporal
    try:
        os.unlink(filepath)
    except Exception:
        pass

    if not ok:
        print("\n[ERROR] No se pudieron subir los datos")
        sys.exit(1)

    print()
    print("  Proceso completado exitosamente")
    sys.exit(0)
