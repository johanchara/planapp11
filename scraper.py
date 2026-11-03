"""
scraper.py - WebFlowers portal downloader using Playwright
"""
import os
import time
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

PORTAL_URL = os.environ.get(
    "WEBFLOWERS_URL",
    "http://webflowersffcalifornia.azurewebsites.net/Default_new.aspx"
)
USUARIO    = os.environ.get("WEBFLOWERS_USER", "Jchara")
CONTRASENA = os.environ.get("WEBFLOWERS_PASS", "Bruno2018!")


def download_sales_report(date_from: str, date_to: str, progress_cb=None) -> str:
    """
    Download SalesReport from WebFlowers portal.
    date_from, date_to: MM/DD/YYYY format
    progress_cb: optional callable(message: str) for streaming progress
    Returns: path to downloaded file (HTML disguised as .xls)
    """

    def log(msg: str):
        if progress_cb:
            progress_cb(msg)

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
            # ── LOGIN ──────────────────────────────────────
            log("Conectando al portal WebFlowers...")
            page.goto(PORTAL_URL, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            log("Iniciando sesion...")
            page.locator("input[placeholder*='User']").fill(USUARIO)
            page.locator("input[type='password']").fill(CONTRASENA)
            page.locator("input[value='Sign In']").click()
            time.sleep(6)
            log("Sesion iniciada correctamente")

            # ── NAVIGATION ─────────────────────────────────
            log("Navegando a Sales Table...")
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

            main_frame.goto(sales_url, wait_until="domcontentloaded")
            time.sleep(4)
            log("En Sales Table")

            # ── FILTROS ────────────────────────────────────
            log("Configurando filtros...")
            frame = page.frame(name="main")
            if not frame:
                for f in page.frames:
                    if "SalesReport" in f.url:
                        frame = f
                        break
            if not frame:
                frame = page.frames[2] if len(page.frames) > 2 else page.main_frame

            # Columns = [All]
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

            # Type = Single-Store
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

            # Dates
            log(f"Configurando fechas: {date_from} → {date_to}")
            frame.evaluate(f"""
                var from = document.getElementById('txtDateFrom');
                from.value = '{date_from}';
                from.dispatchEvent(new Event('change'));
                var to = document.getElementById('txtDateTo');
                to.value = '{date_to}';
                to.dispatchEvent(new Event('change'));
            """)
            time.sleep(0.5)

            # Refresh
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

            # ── DESCARGA ───────────────────────────────────
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

        except Exception as e:
            log(f"Error en descarga: {e}")
            raise
        finally:
            browser.close()
