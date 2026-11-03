"""
main.py - FastAPI application for Plan de Produccion
"""
import asyncio
import json
import os
import threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth import (
    authenticate_user, create_token, get_current_user, get_admin_user,
    hash_password, get_user_by_username
)
from database import get_conn, init_db
from processor import procesar_e_importar, generar_cr, generar_storage

app = FastAPI(title="Plan de Produccion - Falcon Farms")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ── STARTUP ─────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()
    # Create default admin if no users exist
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        admin_pass = os.environ.get("ADMIN_PASSWORD", "admin123")
        admin_user = os.environ.get("ADMIN_USERNAME", "admin")
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?,?,?,?)",
            (admin_user, hash_password(admin_pass), 1, datetime.utcnow().isoformat())
        )
        conn.commit()
        print(f"Admin creado: {admin_user} / {admin_pass}")
    conn.close()


# ── PAGE ROUTES ──────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    with open(os.path.join(static_dir, "index.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/app", response_class=HTMLResponse)
async def app_page():
    with open(os.path.join(static_dir, "app.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    with open(os.path.join(static_dir, "admin.html"), encoding="utf-8") as f:
        return f.read()


# ── AUTH ENDPOINTS ───────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    token = create_token({"sub": user["username"]})
    return {"token": token, "username": user["username"], "is_admin": bool(user["is_admin"])}

@app.get("/api/auth/me")
async def me(current_user=Depends(get_current_user)):
    return {"username": current_user["username"], "is_admin": bool(current_user["is_admin"])}


# ── DISTRIBUCION ENDPOINTS ────────────────────────────────────────────

@app.get("/api/distribucion")
async def get_distribucion(
    fecha: Optional[str] = None,
    dia: Optional[str] = None,
    producto: Optional[str] = None,
    cliente: Optional[str] = None,
    actividad: Optional[str] = None,
    current_user=Depends(get_current_user)
):
    conn = get_conn()
    query = "SELECT * FROM distribucion WHERE 1=1"
    params = []

    if fecha:
        query += " AND due_date=?"
        params.append(fecha)
    if dia and dia.upper() != "ALL":
        query += " AND UPPER(day)=?"
        params.append(dia.upper())
    if producto:
        query += " AND LOWER(product_name) LIKE ?"
        params.append(f"%{producto.lower()}%")
    if cliente:
        query += " AND LOWER(customer) LIKE ?"
        params.append(f"%{cliente.lower()}%")
    if actividad and actividad.upper() != "ALL":
        query += " AND UPPER(activity)=?"
        params.append(actividad.upper())

    query += " ORDER BY due_date, customer_group, customer, product_name"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


class DistribucionUpdate(BaseModel):
    day: Optional[str] = None
    po_inbound: Optional[str] = None
    load_col: Optional[str] = None
    prioridad: Optional[str] = None

@app.put("/api/distribucion/{item_id}")
async def update_distribucion(item_id: int, body: DistribucionUpdate, current_user=Depends(get_current_user)):
    conn = get_conn()
    existing = conn.execute("SELECT id FROM distribucion WHERE id=?", (item_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    updates = {}
    if body.day is not None:
        updates['day'] = body.day
    if body.po_inbound is not None:
        updates['po_inbound'] = body.po_inbound
    if body.load_col is not None:
        updates['load_col'] = body.load_col
    if body.prioridad is not None:
        updates['prioridad'] = body.prioridad

    if updates:
        updates['updated_at'] = datetime.utcnow().isoformat()
        set_clause = ', '.join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [item_id]
        conn.execute(f"UPDATE distribucion SET {set_clause} WHERE id=?", values)
        conn.commit()

    row = conn.execute("SELECT * FROM distribucion WHERE id=?", (item_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/distribucion/{item_id}")
async def delete_distribucion(item_id: int, current_user=Depends(get_admin_user)):
    conn = get_conn()
    conn.execute("DELETE FROM distribucion WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── IMPORT ENDPOINT (SSE streaming) ──────────────────────────────────

class ImportRequest(BaseModel):
    date_from: str
    date_to: str

# Global progress queue
_progress_queues: dict = {}

@app.post("/api/import/start")
async def import_start(req: ImportRequest, current_user=Depends(get_current_user)):
    import uuid
    job_id = str(uuid.uuid4())
    _progress_queues[job_id] = asyncio.Queue()

    def run_import():
        import queue as q_module
        sync_q = _progress_queues[job_id]

        def cb(msg):
            asyncio.run_coroutine_threadsafe(sync_q.put(msg), loop)

        try:
            from scraper import download_sales_report
            filepath = download_sales_report(req.date_from, req.date_to, progress_cb=cb)
            result = procesar_e_importar(filepath, current_user["username"], progress_cb=cb)
            asyncio.run_coroutine_threadsafe(sync_q.put(f"__DONE__:{json.dumps(result)}"), loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(sync_q.put(f"__ERROR__:{str(e)}"), loop)

    loop = asyncio.get_event_loop()
    t = threading.Thread(target=run_import, daemon=True)
    t.start()

    return {"job_id": job_id}


@app.get("/api/import/progress/{job_id}")
async def import_progress(job_id: str, current_user=Depends(get_current_user)):
    if job_id not in _progress_queues:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    async def event_generator():
        q = _progress_queues[job_id]
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=60.0)
                yield f"data: {msg}\n\n"
                if msg.startswith("__DONE__") or msg.startswith("__ERROR__"):
                    del _progress_queues[job_id]
                    break
            except asyncio.TimeoutError:
                yield f"data: __TIMEOUT__\n\n"
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/import/log")
async def import_log(current_user=Depends(get_current_user)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM import_log ORDER BY imported_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── CR ENDPOINT ───────────────────────────────────────────────────────

@app.get("/api/cr")
async def get_cr(fecha: str, current_user=Depends(get_current_user)):
    try:
        return generar_cr(fecha)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── STORAGE ENDPOINT ──────────────────────────────────────────────────

@app.get("/api/storage")
async def get_storage(fecha: str, current_user=Depends(get_current_user)):
    try:
        return generar_storage(fecha)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── USER MANAGEMENT (admin only) ──────────────────────────────────────

@app.get("/api/users")
async def list_users(current_user=Depends(get_admin_user)):
    conn = get_conn()
    rows = conn.execute("SELECT id, username, is_admin, created_at FROM users").fetchall()
    conn.close()
    return [dict(r) for r in rows]


class CreateUserRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False

@app.post("/api/users")
async def create_user(req: CreateUserRequest, current_user=Depends(get_admin_user)):
    conn = get_conn()
    existing = conn.execute("SELECT id FROM users WHERE username=?", (req.username,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="El usuario ya existe")
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?,?,?,?)",
        (req.username, hash_password(req.password), 1 if req.is_admin else 0, datetime.utcnow().isoformat())
    )
    conn.commit()
    user = conn.execute("SELECT id, username, is_admin, created_at FROM users WHERE username=?", (req.username,)).fetchone()
    conn.close()
    return dict(user)


class UpdateUserRequest(BaseModel):
    password: Optional[str] = None
    is_admin: Optional[bool] = None

@app.put("/api/users/{user_id}")
async def update_user(user_id: int, req: UpdateUserRequest, current_user=Depends(get_admin_user)):
    conn = get_conn()
    existing = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if req.password:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(req.password), user_id))
    if req.is_admin is not None:
        conn.execute("UPDATE users SET is_admin=? WHERE id=?", (1 if req.is_admin else 0, user_id))
    conn.commit()
    row = conn.execute("SELECT id, username, is_admin, created_at FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, current_user=Depends(get_admin_user)):
    conn = get_conn()
    target = conn.execute("SELECT id, username FROM users WHERE id=?", (user_id,)).fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target["username"] == current_user["username"]:
        conn.close()
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario")
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
