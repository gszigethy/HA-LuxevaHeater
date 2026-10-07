"""Tests for the Luxeva Heater MQTT coordinator."""

from types import SimpleNamespace
from unittest.mock import Mock

import paho.mqtt.client as mqtt

from custom_components.luxeva_heater.coordinator import LuxevaCoordinator, _parse_status


class ImmediateLoop:
    """Execute thread-safe callbacks synchronously for unit tests."""

    def call_soon_threadsafe(self, callback, *args) -> None:
        callback(*args)


class FakeHass:
    """Minimal Home Assistant stand-in needed by the coordinator."""

    def __init__(self) -> None:
        self.loop = ImmediateLoop()


def make_coordinator() -> LuxevaCoordinator:
    return LuxevaCoordinator(FakeHass(), "00:aa:11:bb:22:cc")


def test_parse_status() -> None:
    assert _parse_status("Msg 1355268, Prg 3, Tmp 21, Hts 24, Tmr 01:42") == {
        "msg": 1355268,
        "prg": 3,
        "tmp": 21,
        "hts": 24,
        "tmr": "01:42",
    }
    assert _parse_status("Msg 7, Prg 0, Tmp -3, Hts 00, Tmr 00:00") == {
        "msg": 7,
        "prg": 0,
        "tmp": -3,
        "hts": 0,
        "tmr": "00:00",
    }
    assert _parse_status("garbage") is None


def test_topics_and_listener_lifecycle() -> None:
    coordinator = make_coordinator()
    assert coordinator.client_id == "00AA11BB22CC"
    assert coordinator.out_topic == "outTopic/00:AA:11:BB:22:CC"
    assert coordinator.in_topic == "inTopic/00:AA:11:BB:22:CC"

    listener = Mock()
    remove = coordinator.add_listener(listener)

    coordinator._notify_listeners()
    listener.assert_called_once_with()

    remove()
    coordinator._notify_listeners()
    listener.assert_called_once_with()

    # Removing twice is harmless.
    remove()


def test_on_connect_subscribes_and_failed_connect_notifies() -> None:
    coordinator = make_coordinator()
    client = Mock()
    listener = Mock()
    coordinator.add_listener(listener)

    coordinator._on_connect(client, None, None, 0)
    client.subscribe.assert_called_once_with(coordinator.out_topic)
    listener.assert_not_called()

    coordinator.data["available"] = True
    coordinator._on_connect(client, None, None, 5)
    assert coordinator.data["available"] is False
    listener.assert_called_once_with()


def test_on_message_updates_state_and_last_level(monkeypatch) -> None:
    coordinator = make_coordinator()
    listener = Mock()
    coordinator.add_listener(listener)
    arm_watchdog = Mock()
    monkeypatch.setattr(coordinator, "_arm_watchdog", arm_watchdog)

    message = SimpleNamespace(
        payload=b"Msg 99, Prg 4, Tmp 23, Hts 26, Tmr 02:15"
    )
    coordinator._on_message(Mock(), None, message)

    assert coordinator.data == {
        "available": True,
        "prg": 4,
        "tmp": 23,
        "hts": 26,
        "tmr": "02:15",
        "msg": 99,
    }
    assert coordinator.last_level == 4
    arm_watchdog.assert_called_once_with()
    listener.assert_called_once_with()


def test_on_message_ignores_invalid_payload(monkeypatch) -> None:
    coordinator = make_coordinator()
    listener = Mock()
    coordinator.add_listener(listener)
    arm_watchdog = Mock()
    monkeypatch.setattr(coordinator, "_arm_watchdog", arm_watchdog)

    coordinator._on_message(
        Mock(),
        None,
        SimpleNamespace(payload=b"not a Luxeva status message"),
    )

    assert coordinator.data["available"] is False
    arm_watchdog.assert_not_called()
    listener.assert_not_called()


def test_disconnect_marks_unavailable_and_notifies(monkeypatch) -> None:
    coordinator = make_coordinator()
    coordinator.data["available"] = True
    listener = Mock()
    coordinator.add_listener(listener)
    disarm = Mock()
    monkeypatch.setattr(coordinator, "_disarm_watchdog", disarm)

    coordinator._on_disconnect(Mock(), None, 1)

    assert coordinator.data["available"] is False
    disarm.assert_called_once_with()
    listener.assert_called_once_with()


def test_publish_when_connected() -> None:
    coordinator = make_coordinator()
    client = Mock()
    client.is_connected.return_value = True
    client.publish.return_value = SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)
    coordinator._client = client

    coordinator.publish("B3")

    client.publish.assert_called_once_with(coordinator.in_topic, "B3")


def test_publish_when_disconnected() -> None:
    coordinator = make_coordinator()
    client = Mock()
    client.is_connected.return_value = False
    coordinator._client = client

    coordinator.publish("B3")

    client.publish.assert_not_called()
