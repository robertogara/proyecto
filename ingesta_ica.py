#!/usr/bin/env python3
"""Poll MITECO ICA data and publish Influx line protocol through MQTT."""

import csv
import io
import logging
import math
import os
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


CSV_URL = os.environ.get("ICA_CSV_URL", "https://ica.miteco.es/datos/ica-ultima-hora.csv")
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "calidad-aire/estaciones")
MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "miteco-ica-ingesta")
MEASUREMENT = "ica_estaciones"
REQUIRED_COLUMNS = {
    "cod_estacion", "nombre", "tipo", "latitud", "longitud", "activa",
    "fecha", "indice", "debido_a",
}


def escape_tag(value):
    return (
        str(value).replace("\\", "\\\\").replace(",", "\\,")
        .replace(" ", "\\ ").replace("=", "\\=")
    )


def escape_string_field(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def make_line_protocol(row):
    if any(not isinstance(row.get(column), str) for column in REQUIRED_COLUMNS):
        return None
    if row["activa"].strip().lower() != "true" or not row["cod_estacion"].strip():
        return None

    raw_index = row["indice"].strip()
    if not raw_index:
        return None

    try:
        original_index = int(raw_index)
        latitude = float(row["latitud"].replace(",", "."))
        longitude = float(row["longitud"].replace(",", "."))
        timestamp = datetime.fromisoformat(row["fecha"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
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
        'nombre="{}",tipo="{}",debido_a="{}",latitud={},longitud={},'
        'indice_original={}i,categoria_ica={}i'
    ).format(
        escape_string_field(row["nombre"]),
        escape_string_field(row["tipo"]),
        escape_string_field(row["debido_a"]),
        format(latitude, ".15g"),
        format(longitude, ".15g"),
        original_index,
        category,
    )
    return "{},cod_estacion={} {} {}".format(
        MEASUREMENT,
        escape_tag(row["cod_estacion"]),
        fields,
        int(timestamp.timestamp()),
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


def _mqtt_string(value):
    encoded = value.encode("utf-8")
    if len(encoded) > 65535:
        raise ValueError("Una cadena MQTT supera el tamaño permitido")
    return len(encoded).to_bytes(2, "big") + encoded


def _mqtt_remaining_length(length):
    if length < 0 or length > 268435455:
        raise ValueError("Tamaño de paquete MQTT fuera de rango")
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length:
            digit |= 0x80
        encoded.append(digit)
        if not length:
            return bytes(encoded)


def _read_mqtt_packet(connection):
    first = connection.recv(1)
    if not first:
        raise OSError("Mosquitto cerró la conexión MQTT")
    multiplier = 1
    remaining = 0
    for _ in range(4):
        raw = connection.recv(1)
        if not raw:
            raise OSError("Conexión MQTT cerrada al leer el paquete")
        digit = raw[0]
        remaining += (digit & 0x7F) * multiplier
        if not digit & 0x80:
            break
        multiplier *= 128
    else:
        raise ValueError("Longitud MQTT inválida")

    payload = bytearray()
    while len(payload) < remaining:
        chunk = connection.recv(remaining - len(payload))
        if not chunk:
            raise OSError("Conexión MQTT cerrada al leer el contenido")
        payload.extend(chunk)
    return first[0], bytes(payload)


def publish_lines(lines):
    if not lines:
        return

    with socket.create_connection((MQTT_HOST, MQTT_PORT), timeout=15) as connection:
        connection.settimeout(15)
        connect_body = (
            _mqtt_string("MQTT")
            + bytes((4, 2))
            + (60).to_bytes(2, "big")
            + _mqtt_string(MQTT_CLIENT_ID)
        )
        connection.sendall(
            bytes((0x10,)) + _mqtt_remaining_length(len(connect_body)) + connect_body
        )
        header, connack = _read_mqtt_packet(connection)
        if header >> 4 != 2 or len(connack) != 2 or connack[1] != 0:
            raise RuntimeError("Mosquitto rechazó la conexión MQTT")

        packet_id = 0
        for line in lines:
            # Each retained topic holds the latest station snapshot for Telegraf.
            tag_set = line.split(" ", 1)[0].split(",", 1)[1]
            station_code = tag_set.split("=", 1)[1]
            station_topic = "{}/{}".format(MQTT_TOPIC, station_code)
            packet_id = packet_id % 65535 + 1
            body = (
                _mqtt_string(station_topic)
                + packet_id.to_bytes(2, "big")
                + line.encode("utf-8")
            )
            connection.sendall(
                bytes((0x33,)) + _mqtt_remaining_length(len(body)) + body
            )
            header, puback = _read_mqtt_packet(connection)
            if (
                header >> 4 != 4
                or len(puback) != 2
                or int.from_bytes(puback, "big") != packet_id
            ):
                raise RuntimeError("Mosquitto no confirmó una lectura ICA")

        connection.sendall(b"\xE0\x00")

def poll_once():
    lines, skipped = fetch_lines()
    publish_lines(lines)
    logging.info(
        "Lecturas ICA publicadas en %s: %d; filas omitidas: %d",
        MQTT_TOPIC, len(lines), skipped,
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
            OSError, urllib.error.URLError, UnicodeError, ValueError,
            csv.Error, RuntimeError,
        ):
            logging.exception("Fallo al consultar MITECO o publicar en MQTT")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
