"""MQTT adapter (FR-01): publish or subscribe to station telemetry when a broker is available.

Topic layout: aurora/<station>/<asset>/<metric>, JSON payload {"ts": ..., "value": ...}.
The prototype runs without a broker (Modbus link instead); docker-compose adds Mosquitto.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


class MqttLink:
    def __init__(self, station: str, host: str = "localhost", port: int = 1883):
        import paho.mqtt.client as mqtt
        self.station = station
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"aurora-{station}")
        self.host, self.port = host, port
        self.connected = False

    def connect(self) -> bool:
        try:
            self.client.connect(self.host, self.port, keepalive=30)
            self.client.loop_start()
            self.connected = True
        except OSError as e:
            log.info("MQTT broker not available (%s); continuing offline", e)
            self.connected = False
        return self.connected

    def publish(self, ts, values: dict):
        if not self.connected:
            return
        for metric, v in values.items():
            asset, name = metric.split(".", 1)
            self.client.publish(f"aurora/{self.station}/{asset}/{name}", json.dumps({"ts": str(ts), "value": v}), qos=0)

    def subscribe(self, on_value):
        def handler(_client, _userdata, msg):
            _, _, asset, name = msg.topic.split("/", 3)
            p = json.loads(msg.payload)
            on_value(p["ts"], f"{asset}.{name}", p["value"])
        self.client.on_message = handler
        self.client.subscribe(f"aurora/{self.station}/#")
