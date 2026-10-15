"""Validate the decoder against real captures and damaged frames."""

import importlib.util
import json
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "decode_ir", ROOT / "scripts/decode_ir.py"
)
decoder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(decoder)
CAPTURES = ROOT / "captures/smart-fr/2026-10-15"


class TestIRDecoder(unittest.TestCase):
    def test_documented_encoder_and_machine_readable_vectors(self):
        document = (ROOT / "docs/ir-protocol.md").read_text()
        scope = {}
        for example in re.findall(r"```python\n(.*?)```", document, re.S):
            exec(example, scope)
        mapping = json.loads((ROOT / "docs/ir-codes.json").read_text())
        self.assertEqual(len(mapping["commands"]), 9)
        for name, vector in mapping["commands"].items():
            with self.subTest(button=name):
                pulses = scope["encode_frame"](vector["device"], vector["command"])
                self.assertEqual(pulses, vector["nominal_frame_with_gap_us"])
                self.assertEqual(sum(map(abs, pulses)), 29250)
                self.assertEqual(
                    decoder.decode_frame(pulses[:-1])["code"], vector["code_hex"]
                )
                measured = vector["measured_frame_without_gap_us"]
                self.assertEqual(
                    decoder.decode_frame(measured)["code"], vector["code_hex"]
                )
                reference = scope["encode_frame"](
                    vector["device"], vector["command"], 30000
                )
                self.assertEqual(sum(map(abs, reference)), 30000)

    def test_captured_commands_and_alternating_sequence(self):
        commands = {
            "power": ("0x3C", "0xCC"),
            "up": ("0x86", "0x05"),
            "power-confirmation": ("0x3C", "0xCC"),
            "down": ("0x86", "0x06"),
            "ok": ("0x86", "0x0D"),
            "program": ("0x86", "0x08"),
            "timer": ("0x86", "0x07"),
            "thermostat": ("0x86", "0x04"),
            "max": ("0x86", "0x0E"),
            "min": ("0x86", "0x0F"),
        }
        for name, expected in commands.items():
            for line in (CAPTURES / f"{name}.jsonl").read_text().splitlines():
                for frame in decoder.split_frames(json.loads(line)["pulses_us"]):
                    with self.subTest(button=name):
                        result = decoder.decode_frame(frame)
                        self.assertEqual(
                            (result["device"], result["command"]), expected
                        )
        sequence = []
        for line in (
            (CAPTURES / "ok-program-alternating.jsonl").read_text().splitlines()
        ):
            frames = decoder.split_frames(json.loads(line)["pulses_us"])
            values = {decoder.decode_frame(f)["command"] for f in frames}
            self.assertEqual(len(values), 1)
            sequence.append(values.pop())
        self.assertEqual(sequence, ["0x0D", "0x08", "0x0D", "0x08"])

    def test_valid_timing_with_bad_checksum_is_rejected(self):
        record = json.loads((CAPTURES / "up.jsonl").read_text().splitlines()[0])
        frame = decoder.split_frames(record["pulses_us"])[0]
        frame[-2] = -580  # Corrupt checksum symbol using another legal symbol.
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            decoder.decode_frame(frame)

    def test_bad_symbol_timing_is_rejected(self):
        record = json.loads((CAPTURES / "up.jsonl").read_text().splitlines()[0])
        frame = decoder.split_frames(record["pulses_us"])[0]
        frame[3] = -2000
        with self.assertRaisesRegex(ValueError, "Unrecognized symbol"):
            decoder.decode_frame(frame)


if __name__ == "__main__":
    unittest.main()
