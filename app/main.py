from __future__ import annotations

import csv
import io
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from .base_datos import fila_a_diccionario, iniciar_base_datos, obtener_conexion
from .modelo_ia import ServicioModeloIA
from .ubicaciones import buscar_departamento_por_provincia, obtener_catalogo_para_api

RUTA_APP = Path(__file__).resolve().parent
RUTA_UPLOADS = RUTA_APP / "static" / "uploads"
RUTA_UPLOADS.mkdir(parents=True, exist_ok=True)
RIESGOS = ["Alto", "Medio", "Bajo"]
VALOR_RIESGO = {"Bajo": 0, "Medio": 1, "Alto": 2}

app = FastAPI(title="AgroIA Perú", version="7.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=RUTA_APP / "static"), name="static")
templates = Jinja2Templates(directory=RUTA_APP / "templates")
servicio_ia: ServicioModeloIA | None = None


class ValidacionTecnica(BaseModel):
    riesgo_real: str
    responsable_validacion: str = ""
    fecha_validacion: str = ""
    observacion_validacion: str = ""


@app.on_event("startup")
def al_iniciar() -> None:
    global servicio_ia
    iniciar_base_datos()
    servicio_ia = ServicioModeloIA()


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "AgroIA Perú activo", "version": "7.0 mapa Perú + geodatos + deploy web"}


@app.get("/api/catalogo")
def catalogo() -> dict[str, Any]:
    return obtener_catalogo_para_api()


@app.post("/api/evaluaciones")
async def crear_evaluacion(
    productor: str = Form(...),
    departamento: str = Form("Sin especificar"),
    cultivo: str = Form(...),
    provincia: str = Form(...),
    distrito: str = Form(...),
    latitud: str = Form(""),
    longitud: str = Form(""),
    altitud_msnm: str = Form(""),
    etapa: str = Form(...),
    fecha_siembra: str = Form(...),
    area_hectareas: float = Form(...),
    temperatura_minima: float = Form(...),
    humedad_suelo: str = Form(...),
    lluvia_acumulada: float = Form(...),
    historial_perdidas: int = Form(...),
    observaciones: str = Form(""),
    origen: str = Form("real"),
    riesgo_real: str = Form(""),
    responsable_validacion: str = Form(""),
    fecha_validacion: str = Form(""),
    observacion_validacion: str = Form(""),
    imagen: UploadFile | None = File(None),
) -> dict[str, Any]:
    if servicio_ia is None:
        raise HTTPException(status_code=503, detail="El modelo IA aún no está listo.")

    latitud_valor = limpiar_numero_opcional(latitud, -18.7, 0.2, "latitud")
    longitud_valor = limpiar_numero_opcional(longitud, -81.6, -68.0, "longitud")
    altitud_valor = limpiar_numero_opcional(altitud_msnm, 0, 6900, "altitud")
    datos = construir_datos_modelo(departamento, cultivo, provincia, distrito, etapa, temperatura_minima, humedad_suelo, lluvia_acumulada, historial_perdidas, area_hectareas)
    resultado = servicio_ia.predecir(datos)
    imagen_url = await guardar_imagen(imagen)
    creado_en = datetime.now().isoformat(timespec="seconds")
    riesgo_real_limpio = limpiar_riesgo_real(riesgo_real)

    with obtener_conexion() as conexion:
        cursor = conexion.execute(
            """
            INSERT INTO evaluaciones (
                productor, departamento, cultivo, provincia, distrito, latitud, longitud, altitud_msnm,
                etapa, fecha_siembra, area_hectareas, temperatura_minima, humedad_suelo, lluvia_acumulada,
                historial_perdidas, observaciones, riesgo, probabilidad, causa,
                recomendaciones, imagen_url, origen, creado_en, riesgo_real,
                puntaje_riesgo, tiempo_ms, factores, metodo_ia, aptitud_cultivo,
                impacto_ubicacion, detalle_aptitud, responsable_validacion,
                fecha_validacion, observacion_validacion, riesgo_modelo, riesgo_reglas,
                bloqueo_critico, zonas_recomendadas, arbol_decision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                productor.strip(),
                datos["departamento"],
                cultivo,
                provincia.strip(),
                distrito.strip(),
                latitud_valor,
                longitud_valor,
                altitud_valor,
                etapa,
                fecha_siembra,
                area_hectareas,
                temperatura_minima,
                humedad_suelo,
                lluvia_acumulada,
                historial_perdidas,
                observaciones.strip(),
                resultado["riesgo"],
                resultado["probabilidad"],
                resultado["causa"],
                json.dumps(resultado["recomendaciones"], ensure_ascii=False),
                imagen_url,
                origen,
                creado_en,
                riesgo_real_limpio,
                resultado["puntaje_riesgo"],
                resultado["tiempo_ms"],
                json.dumps(resultado["factores"], ensure_ascii=False),
                resultado["metodo_ia"],
                resultado["aptitud_cultivo"],
                resultado["impacto_ubicacion"],
                resultado["detalle_aptitud"],
                responsable_validacion.strip(),
                fecha_validacion.strip(),
                observacion_validacion.strip(),
                resultado.get("riesgo_modelo", ""),
                resultado.get("riesgo_reglas", ""),
                int(resultado.get("bloqueo_critico", 0)),
                json.dumps(resultado.get("zonas_recomendadas", []), ensure_ascii=False),
                json.dumps(resultado.get("arbol_decision", {}), ensure_ascii=False),
            ),
        )
        conexion.commit()
        identificador = cursor.lastrowid

    return obtener_evaluacion(identificador)


@app.get("/api/evaluaciones")
def listar_evaluaciones() -> dict[str, Any]:
    with obtener_conexion() as conexion:
        filas = conexion.execute("SELECT * FROM evaluaciones ORDER BY id DESC").fetchall()
    return {"evaluaciones": [fila_a_diccionario(fila) for fila in filas]}


@app.get("/api/evaluaciones/{identificador}")
def obtener_evaluacion(identificador: int) -> dict[str, Any]:
    with obtener_conexion() as conexion:
        fila = conexion.execute("SELECT * FROM evaluaciones WHERE id = ?", (identificador,)).fetchone()
    if fila is None:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada.")
    return fila_a_diccionario(fila)


@app.put("/api/evaluaciones/{identificador}/validacion")
def validar_evaluacion(identificador: int, validacion: ValidacionTecnica) -> dict[str, Any]:
    riesgo_limpio = limpiar_riesgo_real(validacion.riesgo_real)
    if riesgo_limpio is None:
        raise HTTPException(status_code=400, detail="El riesgo real debe ser Alto, Medio o Bajo.")
    fecha = validacion.fecha_validacion.strip() or datetime.now().date().isoformat()
    with obtener_conexion() as conexion:
        fila = conexion.execute("SELECT id FROM evaluaciones WHERE id = ?", (identificador,)).fetchone()
        if fila is None:
            raise HTTPException(status_code=404, detail="Evaluación no encontrada.")
        conexion.execute(
            """
            UPDATE evaluaciones
            SET riesgo_real = ?, responsable_validacion = ?, fecha_validacion = ?, observacion_validacion = ?
            WHERE id = ?
            """,
            (
                riesgo_limpio,
                validacion.responsable_validacion.strip(),
                fecha,
                validacion.observacion_validacion.strip(),
                identificador,
            ),
        )
        conexion.commit()
    return obtener_evaluacion(identificador)


@app.delete("/api/evaluaciones/{identificador}")
def eliminar_evaluacion(identificador: int) -> dict[str, str]:
    with obtener_conexion() as conexion:
        fila = conexion.execute("SELECT imagen_url FROM evaluaciones WHERE id = ?", (identificador,)).fetchone()
        conexion.execute("DELETE FROM evaluaciones WHERE id = ?", (identificador,))
        conexion.commit()
    if fila and fila["imagen_url"]:
        ruta = RUTA_APP / fila["imagen_url"].lstrip("/")
        if ruta.exists() and ruta.is_file():
            ruta.unlink(missing_ok=True)
    return {"mensaje": "Evaluación eliminada"}


@app.post("/api/demo/cargar")
def cargar_demo() -> dict[str, Any]:
    if servicio_ia is None:
        raise HTTPException(status_code=503, detail="El modelo IA aún no está listo.")

    muestras = [
        {"productor": "Comunidad Altoandina Tayacaja", "latitud": -12.3989, "longitud": -74.8667, "altitud_msnm": 3276, "departamento": "Huancavelica", "cultivo": "Papa nativa", "provincia": "Tayacaja", "distrito": "Pampas", "etapa": "Floración", "fecha_siembra": "2026-03-12", "area_hectareas": 2.4, "temperatura_minima": 1.2, "humedad_suelo": "Baja", "lluvia_acumulada": 5.5, "historial_perdidas": 1, "riesgo_real": "Alto", "responsable_validacion": "Técnico demo", "fecha_validacion": "2026-05-10", "observacion_validacion": "Daño visible en hojas por helada.", "observaciones": "Papa en provincia élite, pero con helada y etapa sensible."},
        {"productor": "Caso Costa La Libertad", "latitud": -8.1714, "longitud": -79.0097, "altitud_msnm": 4, "departamento": "La Libertad", "cultivo": "Papa nativa", "provincia": "Trujillo", "distrito": "Moche", "etapa": "Crecimiento", "fecha_siembra": "2026-03-20", "area_hectareas": 1.2, "temperatura_minima": 14.5, "humedad_suelo": "Alta", "lluvia_acumulada": 18.0, "historial_perdidas": 0, "riesgo_real": "Alto", "responsable_validacion": "Técnico demo", "fecha_validacion": "2026-05-10", "observacion_validacion": "El problema principal fue la mala aptitud territorial.", "observaciones": "Demuestra que la ubicación también afecta el riesgo."},
        {"productor": "Cooperativa Quinua San Román", "latitud": -15.4997, "longitud": -70.1333, "altitud_msnm": 3825, "departamento": "Puno", "cultivo": "Quinua", "provincia": "San Román", "distrito": "Juliaca", "etapa": "Maduración", "fecha_siembra": "2026-01-15", "area_hectareas": 6.8, "temperatura_minima": 6.5, "humedad_suelo": "Media", "lluvia_acumulada": 20.0, "historial_perdidas": 0, "riesgo_real": "Bajo", "responsable_validacion": "Técnico demo", "fecha_validacion": "2026-05-09", "observacion_validacion": "Condiciones controladas para quinua.", "observaciones": "Provincia élite para quinua."},
        {"productor": "Productor Maicero Urubamba", "latitud": -13.3047, "longitud": -72.1167, "altitud_msnm": 2871, "departamento": "Cusco", "cultivo": "Maíz", "provincia": "Urubamba", "distrito": "Urubamba", "etapa": "Crecimiento", "fecha_siembra": "2026-02-20", "area_hectareas": 3.1, "temperatura_minima": 8.2, "humedad_suelo": "Media", "lluvia_acumulada": 22.0, "historial_perdidas": 0, "riesgo_real": "Bajo", "responsable_validacion": "Técnico demo", "fecha_validacion": "2026-05-11", "observacion_validacion": "Buen vigor del cultivo.", "observaciones": "Valle favorable para maíz."},
        {"productor": "Ensayo Maíz Altiplano", "latitud": -14.9144, "longitud": -69.8681, "altitud_msnm": 3875, "departamento": "Puno", "cultivo": "Maíz", "provincia": "San Antonio de Putina", "distrito": "Putina", "etapa": "Emergencia", "fecha_siembra": "2026-04-04", "area_hectareas": 1.9, "temperatura_minima": -0.6, "humedad_suelo": "Baja", "lluvia_acumulada": 6.0, "historial_perdidas": 1, "riesgo_real": "Alto", "responsable_validacion": "Técnico demo", "fecha_validacion": "2026-05-08", "observacion_validacion": "Helada afectó emergencia del maíz.", "observaciones": "Caso crítico por helada y mala aptitud."},
        {"productor": "Quinua Huamanga", "latitud": -13.0492, "longitud": -74.1381, "altitud_msnm": 3270, "departamento": "Ayacucho", "cultivo": "Quinua", "provincia": "Huamanga", "distrito": "Quinua", "etapa": "Floración", "fecha_siembra": "2026-02-18", "area_hectareas": 2.2, "temperatura_minima": 5.5, "humedad_suelo": "Muy baja", "lluvia_acumulada": 4.2, "historial_perdidas": 0, "riesgo_real": "Medio", "responsable_validacion": "Técnico demo", "fecha_validacion": "2026-05-11", "observacion_validacion": "Estrés hídrico parcial.", "observaciones": "Buen territorio, pero con déficit hídrico en etapa sensible."},
        {"productor": "Papa Nativa Andahuaylas", "latitud": -13.6533, "longitud": -73.4303, "altitud_msnm": 2820, "departamento": "Apurímac", "cultivo": "Papa nativa", "provincia": "Andahuaylas", "distrito": "Talavera", "etapa": "Llenado de grano", "fecha_siembra": "2026-01-28", "area_hectareas": 4.2, "temperatura_minima": 4.1, "humedad_suelo": "Baja", "lluvia_acumulada": 8.2, "historial_perdidas": 1, "riesgo_real": "Medio", "responsable_validacion": "Técnico demo", "fecha_validacion": "2026-05-10", "observacion_validacion": "Daño moderado por estrés hídrico.", "observaciones": "Provincia fuerte para papa, pero con déficit."},
        {"productor": "Quinua Amazónica Prueba", "latitud": -12.5933, "longitud": -69.1891, "altitud_msnm": 186, "departamento": "Madre de Dios", "cultivo": "Quinua", "provincia": "Tambopata", "distrito": "Tambopata", "etapa": "Emergencia", "fecha_siembra": "2026-04-01", "area_hectareas": 0.8, "temperatura_minima": 22.0, "humedad_suelo": "Alta", "lluvia_acumulada": 72.0, "historial_perdidas": 1, "riesgo_real": "Alto", "responsable_validacion": "Técnico demo", "fecha_validacion": "2026-05-12", "observacion_validacion": "Problemas de hongos por humedad.", "observaciones": "Demuestra zona pésima para quinua por calor y humedad."},
    ]

    creados: list[dict[str, Any]] = []
    for muestra in muestras:
        creado = guardar_muestra_demo(muestra)
        creados.append(creado)
    return {"creados": creados}


@app.delete("/api/demo/limpiar")
def limpiar_demo() -> dict[str, str]:
    with obtener_conexion() as conexion:
        filas = conexion.execute("SELECT imagen_url FROM evaluaciones WHERE origen = 'demo'").fetchall()
        conexion.execute("DELETE FROM evaluaciones WHERE origen = 'demo'")
        conexion.commit()
    for fila in filas:
        if fila["imagen_url"]:
            ruta = RUTA_APP / fila["imagen_url"].lstrip("/")
            if ruta.exists() and ruta.is_file() and ruta.name != "parcela-demo.svg":
                ruta.unlink(missing_ok=True)
    return {"mensaje": "Datos demo eliminados"}


@app.post("/api/importar_csv")
async def importar_csv(archivo: UploadFile = File(...)) -> dict[str, Any]:
    if servicio_ia is None:
        raise HTTPException(status_code=503, detail="El modelo IA aún no está listo.")
    contenido = (await archivo.read()).decode("utf-8-sig")
    lector = csv.DictReader(io.StringIO(contenido))
    creados = 0
    errores: list[str] = []

    for indice, fila in enumerate(lector, start=2):
        try:
            departamento = fila.get("departamento") or buscar_departamento_por_provincia(fila["provincia"])
            latitud_valor = limpiar_numero_opcional(fila.get("latitud", ""), -18.7, 0.2, "latitud")
            longitud_valor = limpiar_numero_opcional(fila.get("longitud", ""), -81.6, -68.0, "longitud")
            altitud_valor = limpiar_numero_opcional(fila.get("altitud_msnm", fila.get("altitud", "")), 0, 6900, "altitud")
            datos = construir_datos_modelo(
                departamento,
                fila["cultivo"],
                fila["provincia"],
                fila["distrito"],
                fila["etapa"],
                float(fila["temperatura_minima"]),
                fila["humedad_suelo"],
                float(fila["lluvia_acumulada"]),
                int(fila["historial_perdidas"]),
                float(fila["area_hectareas"]),
            )
            resultado = servicio_ia.predecir(datos)
            with obtener_conexion() as conexion:
                conexion.execute(
                    """
                    INSERT INTO evaluaciones (
                        productor, departamento, cultivo, provincia, distrito, latitud, longitud, altitud_msnm,
                        etapa, fecha_siembra, area_hectareas, temperatura_minima, humedad_suelo, lluvia_acumulada,
                        historial_perdidas, observaciones, riesgo, probabilidad, causa,
                        recomendaciones, imagen_url, origen, creado_en, riesgo_real,
                        puntaje_riesgo, tiempo_ms, factores, metodo_ia, aptitud_cultivo,
                        impacto_ubicacion, detalle_aptitud, responsable_validacion,
                        fecha_validacion, observacion_validacion, riesgo_modelo, riesgo_reglas,
                        bloqueo_critico, zonas_recomendadas, arbol_decision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fila["productor"], datos["departamento"], datos["cultivo"], datos["provincia"], datos["distrito"],
                        latitud_valor, longitud_valor, altitud_valor, datos["etapa"], fila["fecha_siembra"],
                        datos["area_hectareas"], datos["temperatura_minima"], datos["humedad_suelo"], datos["lluvia_acumulada"],
                        datos["historial_perdidas"], fila.get("observaciones", ""), resultado["riesgo"], resultado["probabilidad"],
                        resultado["causa"], json.dumps(resultado["recomendaciones"], ensure_ascii=False), None, "real",
                        datetime.now().isoformat(timespec="seconds"), limpiar_riesgo_real(fila.get("riesgo_real", "")),
                        resultado["puntaje_riesgo"], resultado["tiempo_ms"], json.dumps(resultado["factores"], ensure_ascii=False), resultado["metodo_ia"],
                        resultado["aptitud_cultivo"], resultado["impacto_ubicacion"], resultado["detalle_aptitud"],
                        fila.get("responsable_validacion", ""), fila.get("fecha_validacion", ""), fila.get("observacion_validacion", ""),
                        resultado.get("riesgo_modelo", ""), resultado.get("riesgo_reglas", ""), int(resultado.get("bloqueo_critico", 0)),
                        json.dumps(resultado.get("zonas_recomendadas", []), ensure_ascii=False), json.dumps(resultado.get("arbol_decision", {}), ensure_ascii=False),
                    ),
                )
                conexion.commit()
            creados += 1
        except Exception as error:
            errores.append(f"Fila {indice}: {error}")
    return {"creados": creados, "errores": errores}


@app.get("/api/resumen")
def resumen() -> dict[str, Any]:
    evaluaciones = obtener_todas_las_evaluaciones()
    total = len(evaluaciones)
    por_riesgo = contar_por(evaluaciones, "riesgo")
    por_cultivo = contar_por(evaluaciones, "cultivo")
    por_origen = contar_por(evaluaciones, "origen")
    por_distrito = contar_por(evaluaciones, "distrito")
    por_provincia = contar_por(evaluaciones, "provincia")
    riesgo_alto = sum(1 for item in evaluaciones if item["riesgo"] == "Alto")
    area_total = round(sum(float(item["area_hectareas"]) for item in evaluaciones), 2)
    area_alta = round(sum(float(item["area_hectareas"]) for item in evaluaciones if item["riesgo"] == "Alto"), 2)
    porcentaje_alto = round((riesgo_alto / total) * 100, 1) if total else 0
    return {
        "total": total,
        "por_riesgo": por_riesgo,
        "por_cultivo": por_cultivo,
        "por_origen": por_origen,
        "por_distrito": por_distrito,
        "por_provincia": por_provincia,
        "riesgo_alto": riesgo_alto,
        "porcentaje_alto": porcentaje_alto,
        "area_total": area_total,
        "area_alta": area_alta,
        "evaluaciones": evaluaciones,
    }


@app.get("/api/metricas")
def metricas_modelo() -> dict[str, Any]:
    evaluaciones = [item for item in obtener_todas_las_evaluaciones() if item.get("riesgo_real") in RIESGOS]
    if not evaluaciones:
        return {"disponible": False, "mensaje": "Agrega validación técnica post-cultivo con riesgo real observado para calcular métricas del modelo."}

    matriz = [[0 for _ in RIESGOS] for _ in RIESGOS]
    for item in evaluaciones:
        real = item["riesgo_real"]
        predicho = item["riesgo"]
        matriz[RIESGOS.index(real)][RIESGOS.index(predicho)] += 1

    total = len(evaluaciones)
    correctos = sum(matriz[i][i] for i in range(len(RIESGOS)))
    accuracy = correctos / total if total else 0
    tasa_error = 1 - accuracy

    precisiones: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    por_clase: dict[str, dict[str, float]] = {}

    for indice, riesgo in enumerate(RIESGOS):
        vp = matriz[indice][indice]
        fp = sum(matriz[fila][indice] for fila in range(len(RIESGOS)) if fila != indice)
        fn = sum(matriz[indice][columna] for columna in range(len(RIESGOS)) if columna != indice)
        precision = vp / (vp + fp) if (vp + fp) else 0
        recall = vp / (vp + fn) if (vp + fn) else 0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0
        precisiones.append(precision)
        recalls.append(recall)
        f1s.append(f1)
        por_clase[riesgo] = {
            "precision": round(precision * 100, 2),
            "recall": round(recall * 100, 2),
            "f1": round(f1 * 100, 2),
            "soporte": sum(matriz[indice]),
        }

    tiempos = [float(item.get("tiempo_ms") or 0) for item in evaluaciones]
    errores_ordinales = [abs(VALOR_RIESGO[item["riesgo"]] - VALOR_RIESGO[item["riesgo_real"]]) for item in evaluaciones]
    variabilidad_error = pstdev(errores_ordinales) if len(errores_ordinales) > 1 else 0
    error_medio_ordinal = mean(errores_ordinales) if errores_ordinales else 0

    return {
        "disponible": True,
        "clases": RIESGOS,
        "matriz": matriz,
        "total_validacion": total,
        "accuracy": round(accuracy * 100, 2),
        "precision": round(mean(precisiones) * 100, 2),
        "recall": round(mean(recalls) * 100, 2),
        "f1_score": round(mean(f1s) * 100, 2),
        "tasa_error": round(tasa_error * 100, 2),
        "tiempo_promedio_ms": round(mean(tiempos), 2) if tiempos else 0,
        "variabilidad_error": round(variabilidad_error, 3),
        "error_medio_ordinal": round(error_medio_ordinal, 3),
        "por_clase": por_clase,
        "nota": "Las métricas se calculan solo con registros que tengan validación técnica post-cultivo. En modo demo, esos valores son etiquetas simuladas para exposición.",
    }


@app.get("/api/exportar_csv")
def exportar_csv() -> StreamingResponse:
    evaluaciones = obtener_todas_las_evaluaciones()
    salida = io.StringIO()
    escritor = csv.writer(salida)
    columnas = [
        "id", "productor", "departamento", "cultivo", "provincia", "distrito", "latitud", "longitud", "altitud_msnm", "etapa", "fecha_siembra", "area_hectareas",
        "temperatura_minima", "humedad_suelo", "lluvia_acumulada", "historial_perdidas", "riesgo", "riesgo_real",
        "probabilidad", "puntaje_riesgo", "aptitud_cultivo", "impacto_ubicacion", "tiempo_ms", "causa", "origen",
        "responsable_validacion", "fecha_validacion", "observacion_validacion", "riesgo_modelo", "riesgo_reglas", "bloqueo_critico", "zonas_recomendadas", "creado_en",
    ]
    escritor.writerow(columnas)
    for fila in evaluaciones:
        escritor.writerow([fila.get(columna, "") for columna in columnas])
    salida.seek(0)
    return StreamingResponse(
        iter([salida.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=agroia_peru_evaluaciones.csv"},
    )


@app.get("/plantilla_csv")
def plantilla_csv() -> FileResponse:
    ruta = RUTA_APP / "static" / "plantilla_agroia.csv"
    return FileResponse(ruta, filename="plantilla_agroia_peru.csv")


async def guardar_imagen(imagen: UploadFile | None) -> str | None:
    if imagen is None or not imagen.filename:
        return None
    extension = Path(imagen.filename).suffix.lower()
    if extension not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        raise HTTPException(status_code=400, detail="Formato de imagen no permitido.")
    nombre = f"{uuid.uuid4().hex}{extension}"
    ruta_destino = RUTA_UPLOADS / nombre
    with ruta_destino.open("wb") as buffer:
        shutil.copyfileobj(imagen.file, buffer)
    return f"/static/uploads/{nombre}"


def construir_datos_modelo(departamento: str, cultivo: str, provincia: str, distrito: str, etapa: str, temperatura_minima: float, humedad_suelo: str, lluvia_acumulada: float, historial_perdidas: int, area_hectareas: float) -> dict[str, Any]:
    departamento_limpio = departamento.strip() if departamento and departamento != "Sin especificar" else buscar_departamento_por_provincia(provincia)
    return {
        "departamento": departamento_limpio,
        "cultivo": cultivo,
        "provincia": provincia,
        "distrito": distrito,
        "etapa": etapa,
        "temperatura_minima": float(temperatura_minima),
        "humedad_suelo": humedad_suelo,
        "lluvia_acumulada": float(lluvia_acumulada),
        "historial_perdidas": int(historial_perdidas),
        "area_hectareas": float(area_hectareas),
    }


def guardar_muestra_demo(muestra: dict[str, Any]) -> dict[str, Any]:
    if servicio_ia is None:
        raise HTTPException(status_code=503, detail="El modelo IA aún no está listo.")
    datos = construir_datos_modelo(
        muestra["departamento"], muestra["cultivo"], muestra["provincia"], muestra["distrito"], muestra["etapa"],
        muestra["temperatura_minima"], muestra["humedad_suelo"], muestra["lluvia_acumulada"],
        muestra["historial_perdidas"], muestra["area_hectareas"]
    )
    resultado = servicio_ia.predecir(datos)
    creado_en = datetime.now().isoformat(timespec="seconds")
    with obtener_conexion() as conexion:
        cursor = conexion.execute(
            """
            INSERT INTO evaluaciones (
                productor, departamento, cultivo, provincia, distrito, latitud, longitud, altitud_msnm,
                etapa, fecha_siembra, area_hectareas, temperatura_minima, humedad_suelo, lluvia_acumulada,
                historial_perdidas, observaciones, riesgo, probabilidad, causa,
                recomendaciones, imagen_url, origen, creado_en, riesgo_real,
                puntaje_riesgo, tiempo_ms, factores, metodo_ia, aptitud_cultivo,
                impacto_ubicacion, detalle_aptitud, responsable_validacion,
                fecha_validacion, observacion_validacion, riesgo_modelo, riesgo_reglas,
                bloqueo_critico, zonas_recomendadas, arbol_decision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                muestra["productor"], datos["departamento"], muestra["cultivo"], muestra["provincia"], muestra["distrito"],
                muestra.get("latitud"), muestra.get("longitud"), muestra.get("altitud_msnm"), muestra["etapa"],
                muestra["fecha_siembra"], muestra["area_hectareas"], muestra["temperatura_minima"], muestra["humedad_suelo"],
                muestra["lluvia_acumulada"], muestra["historial_perdidas"], muestra["observaciones"], resultado["riesgo"],
                resultado["probabilidad"], resultado["causa"], json.dumps(resultado["recomendaciones"], ensure_ascii=False),
                "/static/img/parcela-demo.svg", "demo", creado_en, muestra.get("riesgo_real"), resultado["puntaje_riesgo"],
                resultado["tiempo_ms"], json.dumps(resultado["factores"], ensure_ascii=False), resultado["metodo_ia"],
                resultado["aptitud_cultivo"], resultado["impacto_ubicacion"], resultado["detalle_aptitud"],
                muestra.get("responsable_validacion", ""), muestra.get("fecha_validacion", ""), muestra.get("observacion_validacion", ""),
                resultado.get("riesgo_modelo", ""), resultado.get("riesgo_reglas", ""), int(resultado.get("bloqueo_critico", 0)),
                json.dumps(resultado.get("zonas_recomendadas", []), ensure_ascii=False), json.dumps(resultado.get("arbol_decision", {}), ensure_ascii=False),
            ),
        )
        conexion.commit()
        identificador = cursor.lastrowid
    return obtener_evaluacion(identificador)


def obtener_todas_las_evaluaciones() -> list[dict[str, Any]]:
    with obtener_conexion() as conexion:
        filas = conexion.execute("SELECT * FROM evaluaciones ORDER BY id DESC").fetchall()
    return [fila_a_diccionario(fila) for fila in filas]


def contar_por(evaluaciones: list[dict[str, Any]], campo: str) -> dict[str, int]:
    conteo: dict[str, int] = {}
    for item in evaluaciones:
        clave = str(item.get(campo) or "Sin dato")
        conteo[clave] = conteo.get(clave, 0) + 1
    return conteo



def limpiar_numero_opcional(valor: Any, minimo: float, maximo: float, nombre: str) -> float | None:
    if valor is None or str(valor).strip() == "":
        return None
    try:
        numero = float(str(valor).replace(",", "."))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"El campo {nombre} debe ser numérico.") from error
    if numero < minimo or numero > maximo:
        raise HTTPException(status_code=400, detail=f"El campo {nombre} está fuera del rango esperado para Perú.")
    return numero

def limpiar_riesgo_real(valor: str | None) -> str | None:
    if not valor:
        return None
    valor_limpio = str(valor).strip().capitalize()
    return valor_limpio if valor_limpio in RIESGOS else None