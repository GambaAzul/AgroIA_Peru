## Hola usuario de internet que está aquí, te explico la subida del software, en mi caso usé render, por practicidad, pero eres libre de hacer los cambios que creas necesarios.

1. Crea una cuenta en Render.
2. Sube esta carpeta a un repositorio de GitHub.
3. En Render, apachurra "New +" > "Web Service".
4. Conecta tu repositorio.
5. Render detectará `render.yaml`. Si te pide datos manuales, usa:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Plan: Free
6. Espera el deploy y abre la URL pública que te dé Render.

## Si eres un estudiante un pelin limitado en recursos, como tu servidor, te advierto sobre el plan gratis:

- Sirve para exposición, pruebas y uso académico, te vendrá de perlas para demostrar un punto.
- El servicio puede ""dormir"" si nadie lo usa por varios minutos.
- Al despertar puede tardar cerca de 1 minuto.
- Los archivos locales y la base SQLite pueden perderse si el servicio reinicia o se redepliega.
- Para una clase con 40 alumnos probando una demo, conviene cargar el modo demo durante la exposición y exportar CSV al terminar.

## Cambios Finales

- Mapa georreferenciado del Perú con puntos por latitud y longitud.
- Campos nuevos: latitud, longitud y altitud_msnm.
- Exportación CSV compatible con Power BI incluyendo geodatos.
- Plantilla CSV actualizada.
- Archivos de deploy listos: "render.yaml", "Procfile", "runtime.txt" y Dockerfile compatible con "$PORT".