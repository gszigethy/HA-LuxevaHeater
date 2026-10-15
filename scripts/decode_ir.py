"""Decode demodulated Luxeva captures using the Xiaomi IRP timing model.

Reference: bengtmartensson/IrpTransmogrifier, IrpProtocols.xml, Xiaomi.
Carrier frequency cannot be inferred from these signed pulse durations.
"""

import argparse
import json
from pathlib import Path


def decode_frame(pulses: list[int]) -> dict:
    """Validate one header, ten two-bit symbols, footer, and XOR checksum."""
    if len(pulses) != 23:
        raise ValueError(f"Expected 23 durations, got {len(pulses)}")
    if any(value <= 0 for value in pulses[::2]) or any(
        value >= 0 for value in pulses[1::2]
    ):
        raise ValueError("Expected alternating positive marks and negative spaces")
    if abs(pulses[0] - 1000) > 100 or abs(-pulses[1] - 580) > 100:
        raise ValueError("Header does not match Xiaomi timing model")
    if any(abs(value - 580) > 100 for value in pulses[2::2]):
        raise ValueError("Data/footer marks do not match Xiaomi timing model")
    value = 0
    symbols = []
    for space in pulses[3::2]:
        symbol = min(range(4), key=lambda s: abs(-space - 290 * (s + 2)))
        if abs(-space - 290 * (symbol + 2)) > 100:
            raise ValueError(f"Unrecognized symbol space: {space}")
        symbols.append(symbol)
        value = (value << 2) | symbol
    device, command, checksum = value >> 12, (value >> 4) & 255, value & 15
    expected = (device >> 4) ^ (device & 15) ^ (command >> 4) ^ (command & 15)
    if checksum != expected:
        raise ValueError(f"Checksum mismatch: {checksum:X}, expected {expected:X}")
    return {
        "protocol_model": "Xiaomi",
        "bits": 20,
        "device": f"0x{device:02X}",
        "command": f"0x{command:02X}",
        "checksum": f"0x{checksum:X}",
        "code": f"0x{value:05X}",
        "symbols": symbols,
    }


def split_frames(pulses: list[int]) -> list[list[int]]:
    """Separate repeated frames at recorded idle spaces, retaining all data."""
    frames, pending = [], []
    for duration in pulses:
        if duration < -5000:
            if pending:
                frames.append(pending)
                pending = []
        else:
            pending.append(duration)
    if pending:
        frames.append(pending)
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.captures:
        for line in path.read_text().splitlines():
            record = json.loads(line)
            results = []
            for pulses in split_frames(record["pulses_us"]):
                try:
                    results.append(decode_frame(pulses))
                except ValueError as error:
                    results.append({"decode_error": str(error)})
            print(json.dumps({
                "source": str(path),
                "received_at": record["received_at"],
                "label": record["label"],
                "frames": results,
            }))


if __name__ == "__main__":
    main()
