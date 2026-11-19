# Calidad del aire en España: MQTT, InfluxDB y Grafana

Proyecto de monitorización del Índice de Calidad del Aire (ICA) en estaciones de España. El origen son los datos públicos del CSV horario del MITECO. Para cumplir la arquitectura IoT de la práctica, un publicador los envía por MQTT; Telegraf se suscribe al tópico y escribe las lecturas en InfluxDB; Grafana las consulta y visualiza.

## Arquitectura

```text
CSV público MITECO
       |
       v
ingesta-ica (publicador Python)
       |  Influx Line Protocol por MQTT
       v
Mosquitto: calidad-aire/estaciones
       |
       v
Telegraf (mqtt_consumer + outputs.influxdb)
       |
       v
InfluxDB 1.8: calidad_aire_db / ica_estaciones
       |
       v
Grafana: mapa de estaciones, tabla y serie temporal
```

Los servicios `mosquitto`, `telegraf`, `influxdb`, `grafana` e `ingesta-ica` están conectados a la misma red virtual de Docker Compose, `iot-net`. La fuente MITECO sustituye a los sensores físicos del ejemplo de la guía; sus datos recorren el mismo camino MQTT → Telegraf → InfluxDB → Grafana. El tópico raíz MQTT es `calidad-aire/estaciones`; cada estación publica en `calidad-aire/estaciones/<cod_estacion>`. Los mensajes retenidos usan InfluxDB Line Protocol, así Telegraf recibe la última lectura de cada estación aunque arranque unos segundos después del publicador.

## Requisitos

- Docker Desktop con Docker Compose.
- Acceso a Internet para descargar las imágenes y consultar el CSV público MITECO.

## Arranque

En una copia nueva del repositorio, crea el archivo local de credenciales a partir de la plantilla:

```powershell
Copy-Item .env.example .env
```

Edita `.env` con las credenciales de InfluxDB que quieras usar. El `.env` real está excluido de Git. En el proyecto original ya se conserva un `.env` local con las credenciales que corresponden al volumen existente.

Valida la configuración y levanta todos los servicios:

```powershell
docker compose config
docker compose up -d --build
```

No uses `docker compose down -v`: la opción `-v` borraría los volúmenes persistentes de InfluxDB y Grafana.

## Comprobación

```powershell
docker compose ps
docker compose logs --tail=50 ingesta-ica telegraf
```

En los logs de `ingesta-ica` deben aparecer lecturas publicadas en `calidad-aire/estaciones`; Telegraf debe mostrar que recibe y escribe métricas. El publicador consulta el CSV al arrancar y después cada cinco minutos.

- Grafana: <http://localhost:3000>
- Dashboard aprovisionado: **Calidad del aire en España**
- Fuente Grafana: `InfluxDB-ICA` (`influxdb-ica`)
- Base de datos: `calidad_aire_db`
- Medición: `ica_estaciones`

Para observar un mensaje MQTT de prueba desde otra terminal:

```powershell
docker compose exec mosquitto mosquitto_sub -h localhost -t calidad-aire/estaciones/# -C 1 -v
```

El comando espera al siguiente sondeo de la ingesta y después termina.

## Datos y visualizaciones

Cada lectura válida incluye el código y nombre de estación, tipo de estación, contaminante asociado, coordenadas, categoría ICA e índice original. Las coordenadas provienen del CSV oficial. Las categorías se normalizan a 1–6; por ejemplo, un índice original de `20` se guarda como `categoria_ica=2` e `indice_original=20`.

El dashboard incluye el mapa de estaciones, la tabla de lecturas más desfavorables y la serie temporal de ICA. En el mapa: verde para categorías 1–2, amarillo para 3 y rojo para 4–6. Los datos se publican con la periodicidad del CSV del MITECO (horaria); el sondeo cada cinco minutos no implica que el organismo publique una medición nueva cada cinco minutos. La tabla compara estaciones individuales, no promedios provinciales.

## Archivos principales

- `docker-compose.yml`: servicios, puertos, red virtual y volúmenes persistentes.
- `mosquitto/mosquitto.conf`: broker MQTT.
- `telegraf/telegraf.conf`: suscripción MQTT y salida a InfluxDB.
- `ingesta_ica.py`: descarga, validación y publicación de datos MITECO.
- `grafana-provisioning/datasources/datasource.yml`: fuente InfluxDB de Grafana.
- `grafana-provisioning/dashboards/`: dashboard aprovisionado.
- `.env.example`: plantilla de credenciales locales; no contiene contraseñas reales.

## Fuente

- MITECO, CSV horario: <https://ica.miteco.es/datos/ica-ultima-hora.csv>
- Guía de arquitectura IoT: <https://josejuansanchez.org/iot-dashboard/>
