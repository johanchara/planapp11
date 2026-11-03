# Plan de Producción — Falcon Farms

Aplicación web para gestionar el plan de producción de flores. Reemplaza el archivo Excel compartido con una app en la nube accesible desde cualquier dispositivo.

---

## ¿Qué hace?

- **Login propio**: cada usuario tiene su acceso (el admin crea cuentas)
- **Descarga desde WebFlowers**: cualquier usuario puede importar el reporte de ventas con un clic
- **Plan editable en tiempo real**: todos ven los mismos datos; los cambios se guardan al instante
- **3 pestañas**: Distribución · CR (Cold Room) · Storage
- **Filtros**: fecha, día, cliente, producto, actividad
- **Imprimir CR**: botón de impresión directo desde el navegador
- **Panel admin**: crear/eliminar usuarios, ver historial de importaciones

---

## Despliegue en Render.com (paso a paso)

### 1. Crear repositorio en GitHub

Sube todos los archivos de esta carpeta a un repositorio privado de GitHub.

```
planapp/
├── main.py
├── auth.py
├── database.py
├── processor.py
├── scraper.py
├── requirements.txt
├── Procfile
├── runtime.txt
└── static/
    ├── index.html
    ├── app.html
    └── admin.html
```

### 2. Crear cuenta en Render.com

Ve a [render.com](https://render.com) y crea una cuenta gratuita.

### 3. Crear Web Service

1. En el Dashboard de Render, haz clic en **"New +"** → **"Web Service"**
2. Conecta tu cuenta de GitHub y selecciona el repositorio
3. Configura:
   - **Name**: `falcon-farms-plan` (o el nombre que quieras)
   - **Region**: Oregon (US West) — más cercana a California
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**:
     ```
     pip install -r requirements.txt && python -m playwright install chromium && python -m playwright install-deps chromium
     ```
   - **Start Command**:
     ```
     uvicorn main:app --host 0.0.0.0 --port $PORT
     ```
   - **Plan**: Free (gratis)

### 4. Configurar Variables de Entorno

En la sección **"Environment"** del Web Service, agrega estas variables:

| Variable | Valor | Descripción |
|----------|-------|-------------|
| `SECRET_KEY` | `una-clave-larga-y-aleatoria-aqui` | Clave para cifrar tokens JWT |
| `WEBFLOWERS_USER` | `Jchara` | Usuario de WebFlowers |
| `WEBFLOWERS_PASS` | `Bruno2018!` | Contraseña de WebFlowers |
| `ADMIN_USERNAME` | `admin` | Usuario del primer administrador |
| `ADMIN_PASSWORD` | `elige-una-buena-contrasena` | Contraseña del administrador |

> ⚠️ **Importante**: Cambia `SECRET_KEY` y `ADMIN_PASSWORD` por valores seguros. La `SECRET_KEY` puede ser cualquier cadena larga de texto aleatorio.

### 5. Deploy

Haz clic en **"Create Web Service"**. Render tardará 3-5 minutos en construir e iniciar la app.

Una vez listo, recibirás una URL como:
```
https://falcon-farms-plan.onrender.com
```

### 6. Primer acceso

1. Ve a la URL de tu app
2. Ingresa con las credenciales de admin que configuraste
3. Ve a **Administración** (botón en la barra superior) y crea usuarios para tu equipo
4. Los usuarios ingresan con sus propias credenciales y pueden ver y editar el plan

---

## Uso diario

### Importar datos desde WebFlowers

1. Abre la app e inicia sesión
2. En la pestaña **Distribución**, haz clic en **"Descargar desde WebFlowers"**
3. Selecciona el rango de fechas
4. Haz clic en **"Iniciar Descarga"** y espera el progreso en tiempo real
5. Al terminar, la tabla se actualiza automáticamente para todos los usuarios

### Editar el plan

- **Doble clic** en cualquier celda de: **Día**, **Prioridad**, **PO Inbound**, **Carga**
- El cambio se guarda automáticamente y todos los usuarios lo ven de inmediato

### Generar CR

1. Ve a la pestaña **CR**
2. Selecciona la fecha
3. Haz clic en **"Generar CR"**
4. Usa el botón **"Imprimir CR"** para imprimir o guardar como PDF

### Generar Storage

1. Ve a la pestaña **Storage**
2. Selecciona la fecha
3. Haz clic en **"Generar Storage"**

---

## Notas técnicas

- **Base de datos**: SQLite (`planapp.db`) — se crea automáticamente al iniciar
- **Plan gratuito de Render**: la app "duerme" tras 15 min de inactividad; el primer acceso puede tardar ~30 segundos
- **Para producción**: considera el plan Starter ($7/mes) para que la app esté siempre activa
- **Datos**: todos los datos se guardan en la base de datos del servidor; no se pierden al reiniciar

---

## Lógica de negocio

### Merge al importar
- **Nuevas órdenes**: se insertan automáticamente
- **Órdenes existentes**: se actualizan los datos de WebFlowers (cajas, buckets, etc.) pero se **preservan** los cambios manuales (Día, Prioridad, PO Inbound, Carga)
- **Órdenes canceladas**: se eliminan automáticamente si ya no aparecen en el reporte

### CR
- Incluye órdenes donde `Due Date = fecha` O `Day = nombre_del_día`
- Ordena: sin prioridad primero, luego por prioridad 1, 2, 3...
- Indica LINE2 si el total de buckets supera 4,000
- CD aparece con Buckets = 0
- NO CUENTA se excluye

### Storage
- Excluye CD y NO CUENTA
- VASE: Cajas × Pack
- Resto: Total Buckets ÷ Multiplicador del código de caja
