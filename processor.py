"""
processor.py - Data processing: read SalesReport and merge into SQLite
"""
import hashlib
import json
import pandas as pd
from datetime import datetime
from database import get_conn, get_codigos_map

DIAS_SEMANA = {0:"MONDAY",1:"TUESDAY",2:"WEDNESDAY",3:"THURSDAY",4:"FRIDAY",5:"SATURDAY",6:"SUNDAY"}


def limpiar_col(nombre):
    return str(nombre).strip().replace('\xa0', '').strip()


def encontrar_col(df, nombres):
    for n in nombres:
        if n in df.columns:
            return n
    return None


def encontrar_col_parcial(df, texto):
    for c in df.columns:
        if texto.lower() in c.lower():
            return c
    return None


def encontrar_col_po(df):
    opciones = ['P.O#', 'Final Cust. PO#', 'Final Cust PO#', 'P.O# OUTBOUND', 'P.O#  OUTBOUND']
    for op in opciones:
        if op in df.columns:
            return op
    for c in df.columns:
        if 'final cust' in c.lower() and 'po' in c.lower():
            return c
    for c in df.columns:
        cl = c.replace('\xa0','').replace(' ','').upper()
        if cl in ['P.O#', 'PO#']:
            return c
    return None


def cargar_sales_report(filepath: str) -> pd.DataFrame:
    try:
        tablas = pd.read_html(filepath, header=0)
        if tablas:
            df = tablas[0]
            df.columns = [limpiar_col(str(c)) for c in df.columns]
            return df
    except Exception:
        pass
    try:
        df = pd.read_excel(filepath, header=0, engine='openpyxl')
        df.columns = [limpiar_col(str(c)) for c in df.columns]
        return df
    except Exception:
        pass
    df = pd.read_excel(filepath, header=0, engine='xlrd')
    df.columns = [limpiar_col(str(c)) for c in df.columns]
    return df


def construir_key(po, product, due_date, customer='', boxes=''):
    po_clean = str(po).strip() if po else ''
    if po_clean and po_clean not in ['-', '–', 'nan', '']:
        raw = f"{po_clean}|{product}|{due_date}"
    else:
        raw = f"{customer}|{product}|{due_date}|{boxes}"
    return hashlib.sha256(raw.encode()).hexdigest()


def procesar_e_importar(filepath: str, imported_by: str, progress_cb=None) -> dict:
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    log("Leyendo archivo de ventas...")
    df = cargar_sales_report(filepath)
    log(f"Filas leidas: {len(df)}")

    tabla_buckets = get_codigos_map()

    col_customer_group = encontrar_col_parcial(df, 'Customer Group')
    col_customer   = encontrar_col(df, ['Customer', 'Customer '])
    col_due_date   = encontrar_col_parcial(df, 'Due Date')
    col_po_outbound = encontrar_col_po(df)
    col_product    = encontrar_col_parcial(df, 'Product Name')
    col_pull_date  = encontrar_col(df, ['Pull Date', 'Pull Date '])
    col_box        = encontrar_col(df, ['Box', 'Box '])
    col_pack       = encontrar_col(df, ['Pack', 'Pack '])
    col_boxes      = encontrar_col(df, ['Boxes', 'Boxes '])

    log(f"Columnas: PO={col_po_outbound}, Box={col_box}, Boxes={col_boxes}")

    nuevas_keys = set()
    nuevas_filas = []

    for _, row in df.iterrows():
        box_code = str(row.get(col_box, '') if col_box else '').strip()
        info = tabla_buckets.get(box_code, {'multiplicador': 1, 'actividad': 'WPO', 'categoria': 'WPO'})
        multiplicador = info['multiplicador']

        boxes = 0.0
        if col_boxes:
            try:
                boxes = float(row[col_boxes])
            except Exception:
                boxes = 0.0

        buckets = boxes * multiplicador

        pack = ''
        if col_pack:
            try:
                pack = float(row[col_pack])
            except Exception:
                pack = 0.0

        due_date = None
        due_date_str = ''
        if col_due_date:
            try:
                due_date = pd.to_datetime(row[col_due_date])
                due_date_str = due_date.strftime('%m/%d/%Y')
            except Exception:
                due_date_str = str(row.get(col_due_date, ''))

        pull_date_str = ''
        if col_pull_date:
            try:
                pd_val = pd.to_datetime(row[col_pull_date])
                pull_date_str = pd_val.strftime('%m/%d/%Y')
            except Exception:
                pull_date_str = str(row.get(col_pull_date, ''))

        po_val = ''
        if col_po_outbound:
            raw = str(row.get(col_po_outbound, '')).strip()
            if raw not in ['-', '–', 'nan', '']:
                po_val = raw

        customer = str(row.get(col_customer, '') if col_customer else '').strip()
        product  = str(row.get(col_product, '') if col_product else '').strip()
        cg       = str(row.get(col_customer_group, '') if col_customer_group else '').strip()

        key_hash = construir_key(po_val, product, due_date_str, customer, boxes)
        nuevas_keys.add(key_hash)

        nuevas_filas.append({
            'key_hash': key_hash,
            'customer_group': cg,
            'customer': customer,
            'due_date': due_date_str,
            'po_outbound': po_val,
            'product_name': product,
            'pull_date': pull_date_str,
            'box': box_code,
            'pack': pack,
            'boxes': boxes,
            'activity': info['categoria'],
            'buckets': buckets,
        })

    conn = get_conn()
    now = datetime.utcnow().isoformat()
    added = 0
    updated = 0
    deleted = 0

    # Delete orders no longer in report
    existing_keys = set(
        r[0] for r in conn.execute("SELECT key_hash FROM distribucion").fetchall()
    )
    keys_to_delete = existing_keys - nuevas_keys
    if keys_to_delete:
        placeholders = ','.join('?' * len(keys_to_delete))
        conn.execute(f"DELETE FROM distribucion WHERE key_hash IN ({placeholders})", list(keys_to_delete))
        deleted = len(keys_to_delete)
        log(f"Ordenes eliminadas (canceladas): {deleted}")

    for fila in nuevas_filas:
        existing = conn.execute(
            "SELECT id, day, po_inbound, load_col, prioridad FROM distribucion WHERE key_hash=?",
            (fila['key_hash'],)
        ).fetchone()

        if existing:
            # Update data fields, preserve manual edits
            conn.execute("""
                UPDATE distribucion SET
                    customer_group=?, customer=?, due_date=?, po_outbound=?,
                    product_name=?, pull_date=?, box=?, pack=?, boxes=?,
                    activity=?, buckets=?, updated_at=?
                WHERE key_hash=?
            """, (
                fila['customer_group'], fila['customer'], fila['due_date'],
                fila['po_outbound'], fila['product_name'], fila['pull_date'],
                fila['box'], fila['pack'], fila['boxes'],
                fila['activity'], fila['buckets'], now,
                fila['key_hash']
            ))
            updated += 1
        else:
            conn.execute("""
                INSERT INTO distribucion
                    (key_hash, day, po_inbound, load_col, prioridad,
                     customer_group, customer, due_date, po_outbound,
                     product_name, pull_date, box, pack, boxes, activity, buckets, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                fila['key_hash'], '', '', '', '',
                fila['customer_group'], fila['customer'], fila['due_date'],
                fila['po_outbound'], fila['product_name'], fila['pull_date'],
                fila['box'], fila['pack'], fila['boxes'],
                fila['activity'], fila['buckets'], now
            ))
            added += 1

    # Save sales raw data
    import_time = now
    for _, row in df.iterrows():
        row_dict = {k: (str(v) if pd.notna(v) else '') for k, v in row.items()}
        conn.execute(
            "INSERT INTO sales (imported_at, data_json) VALUES (?,?)",
            (import_time, json.dumps(row_dict))
        )

    # Log the import
    conn.execute("""
        INSERT INTO import_log (imported_at, imported_by, date_from, date_to, rows_added, rows_updated, rows_deleted)
        VALUES (?,?,?,?,?,?,?)
    """, (now, imported_by, '', '', added, updated, deleted))

    conn.commit()
    conn.close()

    log(f"Importacion completa: +{added} nuevas, ~{updated} actualizadas, -{deleted} eliminadas")
    return {"added": added, "updated": updated, "deleted": deleted}


def generar_cr(fecha_str: str) -> dict:
    """
    Generate CR data for a given date (MM/DD/YYYY).
    Returns dict with header info and rows.
    """
    try:
        fecha = datetime.strptime(fecha_str, "%m/%d/%Y")
    except ValueError:
        raise ValueError(f"Formato de fecha invalido: {fecha_str}. Use MM/DD/YYYY")

    nombre_dia = DIAS_SEMANA[fecha.weekday()]
    dias_en = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]
    meses_en = ["January","February","March","April","May","June",
                "July","August","September","October","November","December"]

    label_dia = f"{dias_en[fecha.isoweekday() % 7]}, {meses_en[fecha.month-1]} {fecha.day}, {fecha.year}"

    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM distribucion ORDER BY
            CASE WHEN prioridad='' OR prioridad IS NULL THEN 0 ELSE 1 END,
            CAST(prioridad AS INTEGER),
            due_date, customer_group, customer, product_name
    """).fetchall()
    conn.close()

    tabla_buckets = get_codigos_map()

    cr_rows = []
    total_buckets = 0.0

    # First pass: no priority
    for r in rows:
        row = dict(r)
        if not _incluir_en_cr(row, fecha_str, nombre_dia):
            continue
        if row['activity'] == 'NO CUENTA':
            continue
        if row['prioridad'] and str(row['prioridad']).strip() != '':
            continue

        bucket_val = 0.0 if row['activity'] == 'CD' else (row['buckets'] or 0.0)
        total_buckets += bucket_val
        cr_rows.append(_make_cr_row(row, bucket_val))

    # Second pass: with priority, sorted
    priority_rows = {}
    for r in rows:
        row = dict(r)
        if not _incluir_en_cr(row, fecha_str, nombre_dia):
            continue
        if row['activity'] == 'NO CUENTA':
            continue
        p = str(row.get('prioridad', '')).strip()
        if not p:
            continue
        try:
            pnum = int(p)
        except ValueError:
            continue
        if pnum not in priority_rows:
            priority_rows[pnum] = []
        priority_rows[pnum].append(row)

    for pnum in sorted(priority_rows.keys()):
        for row in priority_rows[pnum]:
            bucket_val = 0.0 if row['activity'] == 'CD' else (row['buckets'] or 0.0)
            total_buckets += bucket_val
            cr_rows.append(_make_cr_row(row, bucket_val))

    line2 = total_buckets > 4000

    return {
        "fecha": fecha_str,
        "label_dia": label_dia,
        "total_buckets": total_buckets,
        "line2": line2,
        "rows": cr_rows,
    }


def _incluir_en_cr(row: dict, fecha_str: str, nombre_dia: str) -> bool:
    due = str(row.get('due_date', '')).strip()
    day_col = str(row.get('day', '')).strip().upper()
    return due == fecha_str or day_col == nombre_dia


def _make_cr_row(row: dict, bucket_val: float) -> dict:
    return {
        "id": row['id'],
        "prioridad": row.get('prioridad', ''),
        "po_inbound": row.get('po_inbound', ''),
        "customer": row.get('customer', ''),
        "due_date": row.get('due_date', ''),
        "po_outbound": row.get('po_outbound', ''),
        "product_name": row.get('product_name', ''),
        "pull_date": row.get('pull_date', ''),
        "box": row.get('box', ''),
        "pack": row.get('pack', ''),
        "activity": row.get('activity', ''),
        "total": bucket_val,
        "is_cd": row.get('activity', '') == 'CD',
    }


def generar_storage(fecha_str: str) -> dict:
    """Generate Storage summary for a given date."""
    cr_data = generar_cr(fecha_str)
    tabla_buckets = get_codigos_map()

    fecha = datetime.strptime(fecha_str, "%m/%d/%Y")
    nombre_dia = DIAS_SEMANA[fecha.weekday()]

    conn = get_conn()
    dist_rows = conn.execute("SELECT * FROM distribucion").fetchall()
    conn.close()
    dist_map = {}
    for r in dist_rows:
        row = dict(r)
        key = (row.get('box', ''), row.get('product_name', ''))
        if _incluir_en_cr(row, fecha_str, nombre_dia):
            dist_map[key] = row

    box_data = {}

    for cr_row in cr_data['rows']:
        if cr_row['is_cd']:
            continue
        box = cr_row['box']
        activity = cr_row['activity']
        total_bucket = cr_row['total']
        pack = cr_row.get('pack') or 0

        info = tabla_buckets.get(box, {'multiplicador': 1, 'actividad': activity, 'categoria': activity})
        mult = info['multiplicador'] or 1

        is_vase = 'VASE' in str(activity).upper()

        if is_vase:
            # Cajas from DISTRIBUCION
            dk = (box, cr_row['product_name'])
            dist_row = dist_map.get(dk)
            cajas = float(dist_row['boxes']) if dist_row else 0.0
            vases = cajas * float(pack) if pack else 0.0
        else:
            cajas = total_bucket / mult if mult > 0 else 0.0
            vases = 0.0

        if box not in box_data:
            box_data[box] = {'box': box, 'cajas': 0.0, 'vases': 0.0, 'activity': activity}
        box_data[box]['cajas'] += cajas
        box_data[box]['vases'] += vases

    storage_rows = list(box_data.values())
    total_cajas = sum(r['cajas'] for r in storage_rows)
    total_vases = sum(r['vases'] for r in storage_rows)

    return {
        "fecha": fecha_str,
        "label_dia": cr_data['label_dia'],
        "rows": storage_rows,
        "total_cajas": total_cajas,
        "total_vases": total_vases,
    }
