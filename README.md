# Calidad del aire en España

Este proyecto consulta cada cinco minutos el CSV horario oficial del Índice
Nacional de Calidad del Aire (ICA) del MITECO y escribe los datos de las
estaciones activas en InfluxDB 1.8. Grafana 12.4.15 aprovisiona una fuente
InfluxDB y el dashboard con un mapa Geomap de OpenStreetMap y una tabla de
estaciones ordenada por categoría ICA.

La ingesta usa la base `calidad_aire_db` y conserva los volúmenes existentes
`influxdb_data` y `grafana_data`; no es necesario borrar ni migrar datos. Los
servicios Mosquitto y Telegraf, así como la antigua ingesta de sismos, ya no se
usan.

## Aplicar los cambios

Desde esta carpeta, valida la configuración y levanta los servicios:

```shell
docker compose config
docker compose up -d --remove-orphans
```

`--remove-orphans` retira los contenedores Mosquitto/Telegraf antiguos del
proyecto, pero no borra los volúmenes. No ejecutes `docker compose down -v`.

La ingesta hace una consulta inmediata al arrancar y después cada cinco minutos.
Consulta su estado y registros con:

```shell
docker compose ps
docker compose logs -f ingesta-ica
```

Grafana estará disponible en <http://localhost:3000>. Abre el dashboard
**Calidad del aire en España** en la carpeta del mismo nombre. La fuente de
datos aprovisionada `InfluxDB-ICA` apunta a `calidad_aire_db`.

## Datos y visualizaciones

La fuente es <https://ica.miteco.es/datos/ica-ultima-hora.csv> y su diccionario
oficial está en <https://ica.miteco.es/datos/DICCIONARIO_DE_DATOS.txt>. Se
ignoran estaciones inactivas, índices vacíos, índice 0 y filas inválidas. La
medición `ica_estaciones` guarda por estación las coordenadas del CSV, el
timestamp UTC, el valor original del índice y su categoría normalizada (por
ejemplo, `20` se conserva como `indice_original=20` y `categoria_ica=2`).

El mapa colorea las categorías 1-2 en verde, 3 en amarillo y 4-6 en rojo. Los
detalles de cada estación incluyen nombre, tipo, categoría, contaminante
causante y hora del dato. La tabla compara estaciones de medición individuales;
no muestra promedios provinciales.
