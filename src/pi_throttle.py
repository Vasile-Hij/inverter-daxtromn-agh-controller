"""Raspberry Pi throttle monitor: detects undervoltage and other power issues."""

import subprocess


THROTTLE_FLAGS = {
    0x1: "under-voltage",
    0x2: "arm-frequency-capped",
    0x4: "currently-throttled",
    0x8: "soft-temperature-limit",
}


def read_throttled_hex():
    result = subprocess.run(
        ["vcgencmd", "get_throttled"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if not output.startswith("throttled="):
        return None
    return int(output.split("=")[1], 16)


def decode_active_flags(throttled_hex):
    active = []
    for bitmask, label in THROTTLE_FLAGS.items():
        if throttled_hex & bitmask:
            active.append(label)
    return active
