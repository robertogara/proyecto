#!/usr/bin/env python3
"""Poll MITECO's hourly air-quality CSV and write station readings to InfluxDB."""

import base64
import csv
import io
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


CSV_URL = os.environ.get(
    "ICA_CSV_URL", "https://ica.miteco.es/datos/ica-ultima-hora.csv"
)
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://influxdb:8086").rstrip("/")
INFLUXDB_DATABASE = os.environ.get("INFLUXDB_DATABASE", "calidad_aire_db")
INFLUXDB_USERNAME = os.environ.get("INFLUXDB_USERNAME", "root")
INFLUXDB_PASSWORD = os.environ.get("INFLUXDB_PASSWORD", "root")
MEASUREMENT = "ica_estaciones"
REQUIRED_COLUMNS = {
    "cod_estacion",
    "nombre",
    "tipo",
    "latitud",
    "longitud",
    "activa",
    "fecha",
    "indice",
    "debido_a",
}


def escape_tag(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(" ", "\\ ")
        .replace("=", "\\=")
    )


def escape_string_field(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def make_line_protocol(row):
    if any(not isinstance(row.get(column), str) for column in REQUIRED_COLUMNS):
        return None
    if row["activa"].strip().lower() != "true":
        return None
    if not row["cod_estacion"].strip():
        return None

    raw_index = row["indice"].strip()
    if not raw_index:
        return None

    try:
        original_index = int(raw_index)
        latitude = float(row["latitud"])
        longitude = float(row["longitud"])
        timestamp = datetime.fromisoformat(row["fecha"]).replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError, OverflowError):
        return None

    category = original_index // 10 if original_index >= 10 else original_index
    if (
        category not in range(1, 7)
        or original_index not in (category, category * 10)
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return None

    fields = (
        "nombre=\"{}\",tipo=\"{}\",debido_a=\"{}\","
        "latitud={},longitud={},indice_original={}i,categoria_ica={}i"
    ).format(
        escape_string_field(row["nombre"]),
        escape_string_field(row["tipo"]),
        escape_string_field(row["debido_a"]),
        format(latitude, ".15g"),
        format(longitude, ".15g"),
        original_index,
        category,
    )
    timestamp_seconds = int(timestamp.timestamp())
    return "{}{} {} {}".format(
        MEASUREMENT,
        ",cod_estacion={}".format(escape_tag(row["cod_estacion"])),
        fields,
        timestamp_seconds,
    )


def fetch_lines():
    request = urllib.request.Request(
        CSV_URL, headers={"User-Agent": "MITECO-ICA-Ingesta/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        contents = response.read().decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(contents))
    if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
        raise ValueError("El CSV de MITECO no contiene todas las columnas esperadas")

    lines = []
    skipped = 0
    for row in reader:
        line = make_line_protocol(row)
        if line is None:
            skipped += 1
        else:
            lines.append(line)
    return lines, skipped


def write_lines(lines):
    if not lines:
        return

    query = urllib.parse.urlencode(
        {"db": INFLUXDB_DATABASE, "precision": "s"}
    )
    request = urllib.request.Request(
        "{}/write?{}".format(INFLUXDB_URL, query),
        data=("\n".join(lines) + "\n").encode("utf-8"),
        headers={
            "Authorization": "Basic {}".format(
                base64.b64encode(
                    "{}:{}".format(INFLUXDB_USERNAME, INFLUXDB_PASSWORD).encode(
                        "utf-8"
                    )
                ).decode("ascii")
            ),
            "Content-Type": "text/plain; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in (200, 204):
            raise RuntimeError(
                "InfluxDB rechazó la escritura (HTTP {})".format(response.status)
            )


def poll_once():
    lines, skipped = fetch_lines()
    write_lines(lines)
    logging.info(
        "Estaciones ICA escritas: %d; filas omitidas: %d", len(lines), skipped
    )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    while True:
        try:
            poll_once()
        except (
            OSError,
            urllib.error.URLError,
            UnicodeError,
            ValueError,
            csv.Error,
            RuntimeError,
        ):
            logging.exception("Fallo al consultar MITECO o escribir en InfluxDB")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
