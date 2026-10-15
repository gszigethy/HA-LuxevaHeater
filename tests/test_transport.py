"""Real paho socket exchange against a loopback MQTT wire fixture, no heater."""

import asyncio
from contextlib import contextmanager
import socketserver
import struct
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from custom_components.luxeva_heater.coordinator import LuxevaCoordinator
from custom_components.luxeva_heater.local import async_probe_broker


def mqtt_packet(header, body):
    length = len(body)
    encoded = bytearray([header])
    while True:
        digit = length % 128
        length //= 128
        encoded.append(digit | (128 if length else 0))
        if not length:
            break
    return bytes(encoded) + body


def mqtt_string(value):
    value = value.encode()
    return struct.pack("!H", len(value)) + value


@contextmanager
def broker_fixture(refused=False):
    received = []
    status_topic = "outTopic/00:AA:11:BB:22:CC"
    command_topic = "inTopic/00:AA:11:BB:22:CC"

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            while first := self.rfile.read(1):
                length, multiplier = 0, 1
                while True:
                    digit = self.rfile.read(1)[0]
                    length += (digit & 127) * multiplier
                    if not digit & 128:
                        break
                    multiplier *= 128
                payload = self.rfile.read(length)
                received.append((first[0] >> 4, payload))
                kind = first[0] >> 4
                if kind == 1:
                    self.wfile.write(
                        b"\x20\x02\x00" + (b"\x05" if refused else b"\x00")
                    )
                elif kind == 8:
                    self.wfile.write(mqtt_packet(0x90, payload[:2] + b"\x00"))
                    size = struct.unpack("!H", payload[2:4])[0]
                    topic = payload[4 : 4 + size].decode()
                    if topic == status_topic:
                        # A retained old status cannot establish availability.
                        old = (
                            mqtt_string(topic)
                            + b"Msg 99, Prg 6, Tmp 99, Hts 00, Tmr 00:00"
                        )
                        self.wfile.write(mqtt_packet(0x31, old))
                        for sequence, temperature in ((500, 36), (1, 37)):
                            status = f"Msg {sequence}, Prg 1, Tmp {temperature}, Hts 00, Tmr 00:59".encode()
                            self.wfile.write(
                                mqtt_packet(0x30, mqtt_string(topic) + status)
                            )
                    elif topic == command_topic:
                        self.wfile.write(mqtt_packet(0x30, mqtt_string(topic) + b"T3"))
                elif kind == 12:
                    self.wfile.write(b"\xd0\x00")
                elif kind == 14:
                    return

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

    with Server(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            yield server.server_address[1], received
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_real_socket_probe_checks_connack():
    async def run(port):
        hass = SimpleNamespace(async_add_executor_job=asyncio.to_thread)
        return await async_probe_broker(hass, {"broker": "127.0.0.1", "port": port})

    with broker_fixture() as (port, _):
        assert asyncio.run(run(port))
    with broker_fixture(refused=True) as (port, _):
        assert not asyncio.run(run(port))


def test_native_status_heartbeat_and_counter_reset_are_preserved():
    async def run(port):
        loop = asyncio.get_running_loop()
        hass = SimpleNamespace(loop=loop, async_add_executor_job=asyncio.to_thread)
        coordinator = LuxevaCoordinator(hass, "00:AA:11:BB:22:CC", "127.0.0.1", port)
        coordinator._arm_watchdog = Mock()
        coordinator.control = SimpleNamespace(
            managed=True,
            latched=False,
            on_status=Mock(),
            on_command=Mock(),
            note_command=Mock(),
        )
        seen = []
        coordinator.add_listener(
            lambda: seen.append((coordinator.data["msg"], coordinator.data["tmp"]))
        )
        await coordinator.async_connect()
        try:
            async with asyncio.timeout(5):
                while len(seen) < 2 or not coordinator.control.on_command.called:
                    await asyncio.sleep(0.01)
            assert seen == [(500, 36), (1, 37)]
            assert coordinator.data["available"]
            coordinator.control.on_command.assert_called_once_with("T3")
            assert coordinator.publish("B3")
            await asyncio.sleep(0.05)
        finally:
            await coordinator.async_disconnect()

    with broker_fixture() as (port, received):
        asyncio.run(run(port))
    publications = [payload for kind, payload in received if kind == 3]
    assert any(payload.endswith(b"B3") for payload in publications)
