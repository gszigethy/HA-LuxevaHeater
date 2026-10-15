"""Passively record one Luxeva heater's MQTT command and status topics.

Requires paho-mqtt (1.6 or 2.x). No publishes, will, or wildcard subscriptions.
Raw captures include the device MAC; store them outside public evidence paths.
"""

import argparse
import base64
import json
import os
import re
import signal
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

STATUS = re.compile(
    r"Msg\s+(\d+),\s*Prg\s+(\d+),\s*Tmp\s+(-?\d+),\s*Hts\s+(-?\d+),\s*Tmr\s+(\d{2}:\d{2})"
)


def parse_status(payload):
    match = STATUS.fullmatch(payload.strip())
    if not match:
        return None
    msg, prg, tmp, hts, tmr = match.groups()
    return {"msg": int(msg), "prg": int(prg), "tmp": int(tmp),
            "hts": int(hts), "tmr": tmr}


def main():
    import paho.mqtt.client as mqtt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", required=True)
    parser.add_argument("--broker", default="iot.luxeva.com.tr")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--label-file", type=Path)
    args = parser.parse_args()
    compact = re.sub(r"[:-]", "", args.mac).upper()
    if not re.fullmatch(r"[0-9A-F]{12}", compact):
        parser.error("MAC must contain exactly 12 hexadecimal digits")
    mac = ":".join(compact[i:i+2] for i in range(0, 12, 2))
    topics = {f"inTopic/{mac}": "command", f"outTopic/{mac}": "status"}
    os.umask(0o077)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = args.output.open("a", buffering=1)
    last_state = None

    def emit(kind, **data):
        record = {"received_at": datetime.now(UTC).isoformat(),
                  "monotonic_ns": time.monotonic_ns(), "kind": kind, **data}
        output.write(json.dumps(record, ensure_ascii=True) + "\n")

    client_id = "luxcap-" + uuid.uuid4().hex[:12]
    options = {"client_id": client_id, "clean_session": True,
               "protocol": mqtt.MQTTv311}
    if hasattr(mqtt, "CallbackAPIVersion"):
        options["callback_api_version"] = mqtt.CallbackAPIVersion.VERSION1
    client = mqtt.Client(**options)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    def on_connect(client, userdata, flags, rc, *extra):
        emit("connect", result=str(rc), session_flags=flags)
        if rc == 0:
            result, mid = client.subscribe([(topic, 0) for topic in topics])
            emit("subscribe_requested", mid=mid, result=result, topics=list(topics))
            print("CONNECTED; subscribing to both exact device topics", flush=True)
        else:
            print(f"CONNECTION REJECTED: {rc}", flush=True)

    def on_subscribe(client, userdata, mid, granted, *extra):
        granted = [int(q) for q in granted]
        emit("subscribed", mid=mid, granted_qos=granted)
        print(f"SUBACK: {granted} (128 means rejected)", flush=True)

    def on_disconnect(client, userdata, rc, *extra):
        emit("disconnect", result=str(rc))
        print(f"DISCONNECTED: {rc}", flush=True)

    def on_message(client, userdata, message):
        nonlocal last_state
        label = "unlabelled"
        if args.label_file:
            try:
                label = args.label_file.read_text().strip() or label
            except FileNotFoundError:
                pass
        text = message.payload.decode("utf-8", errors="replace")
        direction = topics.get(message.topic, "unexpected")
        state = parse_status(text) if direction == "status" else None
        changes = None
        if state is not None:
            # Preserve Msg in raw/parsed evidence, omit it from change summaries.
            current = {k: v for k, v in state.items() if k != "msg"}
            changes = current if last_state is None else {
                k: {"before": last_state[k], "after": v}
                for k, v in current.items() if last_state[k] != v
            }
            last_state = current
        emit("message", label=label, direction=direction, topic=message.topic,
             payload=text, payload_b64=base64.b64encode(message.payload).decode("ascii"),
             qos=message.qos, retain=message.retain, dup=message.dup,
             status=state, changes=changes)
        if direction == "command" or changes:
            print(json.dumps({"direction": direction, "label": label,
                              "payload": text, "changes": changes}), flush=True)

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    emit("start", broker=args.broker, port=args.port, client_id=client_id,
         protocol="MQTTv311", topics=list(topics), publish_enabled=False)

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        client.connect(args.broker, args.port, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        emit("stop")
    finally:
        client.disconnect()
        output.close()


if __name__ == "__main__":
    main()
