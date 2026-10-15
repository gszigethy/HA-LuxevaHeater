"""Collect ESPHome raw IR logs and preserve complete signed pulse arrays.

Requires pyserial (included with ESPHome). Serial modem lines stay inactive;
the collector does not reset, flash, or transmit to the device.
"""

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

# Adapted from ../HA-Webasto-Cool-Top-Trail/scripts/capture_ir_serial.py.
# Luxeva protocol is unknown: preserve raw evidence without an AC decoder.

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
RAW_LOG = re.compile(r"\[remote\.raw(?::[^\]]+)?\]:?\s?(.*)")
NUMBERS = re.compile(r"[\s\d,+-]+")


class RawLogAssembler:
    """Assemble one ESPHome raw dump across its 256-character log chunks."""

    def __init__(self) -> None:
        self.pending: list[int] = []

    def flush(self) -> list[list[int]]:
        """Preserve a pending frame, including partial/noisy input."""
        if not self.pending:
            return []
        frame, self.pending = self.pending, []
        return [frame]

    def feed(self, line: str) -> list[list[int]]:
        """Return newly completed frames without discarding invalid evidence."""
        match = RAW_LOG.search(ANSI.sub("", line))
        if not match:
            return []
        body = match.group(1)
        frames = []
        if body.startswith("Received Raw:"):
            frames.extend(self.flush())
            body = body.removeprefix("Received Raw:")
        elif not self.pending:
            return []
        if not NUMBERS.fullmatch(body):
            return frames
        self.pending.extend(int(value) for value in re.findall(r"[+-]?\d+", body))
        return frames


def describe_frame(pulses: list[int], label: str) -> dict:
    """Store evidence even if the protocol is not yet known."""
    record = {
        "received_at": datetime.now(UTC).isoformat(),
        "label": label,
        "source_kind": "live ESPHome raw receiver log",
        "pulses_us": pulses,
    }
    return record


def main() -> None:
    """Read an attached receiver and append timestamped JSONL records."""
    import serial

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--raw-log", type=Path, help="Also preserve original serial bytes"
    )
    parser.add_argument("--label", default="unlabelled")
    parser.add_argument("--label-file", type=Path)
    parser.add_argument(
        "--seconds", type=float, default=0, help="0 listens until stopped"
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.raw_log:
        args.raw_log.parent.mkdir(parents=True, exist_ok=True)

    port = serial.Serial(port=None, baudrate=115200, timeout=0.1)
    port.dtr = False
    port.rts = False
    port.port = args.port
    port.open()
    assembler = RawLogAssembler()
    started = last_input = time.monotonic()
    buffer = bytearray()

    def save(frames: list[list[int]]) -> None:
        for pulses in frames:
            label = args.label
            if args.label_file and args.label_file.exists():
                label = args.label_file.read_text().strip() or label
            record = describe_frame(pulses, label)
            with args.output.open("a") as output:
                output.write(json.dumps(record) + "\n")
            summary = {
                key: value for key, value in record.items() if key != "pulses_us"
            }
            print(json.dumps({"pulse_count": len(pulses), **summary}), flush=True)

    print(f"Listening on {args.port}; writing {args.output}", flush=True)
    try:
        while not args.seconds or time.monotonic() - started < args.seconds:
            chunk = port.read(4096)
            if chunk:
                if args.raw_log:
                    with args.raw_log.open("ab") as raw_output:
                        raw_output.write(chunk)
                last_input = time.monotonic()
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, remaining = buffer.partition(b"\n")
                    buffer[:] = remaining
                    save(assembler.feed(line.decode(errors="replace")))
            elif time.monotonic() - last_input > 0.5:
                save(assembler.flush())
    except KeyboardInterrupt:
        pass
    finally:
        save(assembler.flush())
        port.close()


if __name__ == "__main__":
    main()
