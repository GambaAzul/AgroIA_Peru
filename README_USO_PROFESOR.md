AgroIA Perú es una aplicación web para exposición educativa. Predice riesgo productivo en cultivos andinos usando un modelo híbrido: Random Forest, reglas agroclimáticas, aptitud territorial y validación técnica post-cultivo.

## Cómo iniciar en una computadora local

1. Instalar Docker Desktop.
2. Abrir Docker Desktop y esperar que diga "Engine running".
3. Descomprimir esta carpeta.
4. Hacer doble clic en "INICIAR_AGROIA.bat".
5. Abrir "http://localhost:8000" en el navegador si no se abre automáticamente.

## Cómo "apagarlo"

Hacer doble clic en "DETENER_AGROIA.bat".

## Cómo usar para exposición

1. Cargar modo demo.
2. Mostrar el panel general.
3. Explicar el mapa georreferenciado del Perú.
4. Ir a "Nueva evaluación".
5. Registrar una parcela agrícola con latitud, longitud y altitud.
6. Ejecutar el análisis IA.
7. Mostrar el árbol IA animado.
8. Exportar el CSV para Power BI.

## Novedades Finales

- Mapa visual del Perú con alertas georreferenciadas.
- Los puntos se ubican usando latitud y longitud, no posiciones inventadas.
- Campos nuevos en el formulario: latitud, longitud y altitud_msnm.
- Exportación CSV compatible con Power BI incluyendo geodatos.
- Plantilla CSV actualizada.
- Logo institucional del Colegio de Ingenieros visible en la interfaz.

## Nota técnica del desarrollador

El mapa del Perú es una representación visual esquemática. La ubicación de alertas se calcula con coordenadas reales o referencias locales cargadas en el catálogo. Para producción exacta, se recomienda reemplazar el catálogo demostrativo por UBIGEO oficial, geocodificación completa o una capa GeoJSON oficial.