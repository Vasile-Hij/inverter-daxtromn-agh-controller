import sys
import time

import serial

PYLON_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
PYLON_BAUD = 9600
PYLON_ADR = 0x02  # first battery address per Pylon V3.5 protocol (starts from 2)
PYLON_CID1 = 0x46
PYLON_CID2_ANALOG = 0x42
PYLON_CID2_SYSTEM_ANALOG = 0x61
PYLON_TIMEOUT_SECONDS = 2
PYLON_RESPONSE_OK = 0x00

PYLON_RESPONSE_CODES = {
    0x00: "Normal",
    0x01: "VER error",
    0x02: "CHKSUM error",
    0x03: "LCHKSUM error",
    0x04: "CID2 invalid",
    0x05: "Command format error",
    0x06: "Invalid data",
    0x90: "ADR error",
    0x91: "Communication error",
}


def pylon_ascii_checksum(payload):
    total = sum(ord(char) for char in payload) % 65536
    return f"{(~total + 1) & 0xFFFF:04X}"


def build_pylon_query(adr, cid2):
    body = f"20{adr:02X}{PYLON_CID1:02X}{cid2:02X}0000"
    frame = "~" + body + pylon_ascii_checksum(body) + "\r"
    return frame.encode("ascii")


def parse_pylon_system_analog(info_hex):
    voltage_v = int(info_hex[0:4], 16) / 1000
    current_raw = int(info_hex[4:8], 16)
    current_a = (current_raw - 0x10000 if current_raw >= 0x8000 else current_raw) / 1000
    soc_pct = int(info_hex[8:10], 16)
    avg_cycles = int(info_hex[10:14], 16)
    max_cycles = int(info_hex[14:18], 16)
    avg_soh_pct = int(info_hex[18:20], 16)
    min_soh_pct = int(info_hex[20:22], 16)
    return {
        "voltage_v": voltage_v,
        "current_a": current_a,
        "soc_pct": soc_pct,
        "avg_cycles": avg_cycles,
        "max_cycles": max_cycles,
        "avg_soh_pct": avg_soh_pct,
        "min_soh_pct": min_soh_pct,
    }


def query_system_analog(ser):
    command = build_pylon_query(PYLON_ADR, PYLON_CID2_SYSTEM_ANALOG)
    print("TX:", command)
    ser.reset_input_buffer()
    ser.write(command)

    response = ser.read_until(b"\r")
    print("RX:", response)

    if not response:
        print("no response (timeout) -- check wiring, A/B polarity, baud rate, and address")
        return

    if not response.startswith(b"~") or not response.endswith(b"\r"):
        print("malformed frame (missing SOI/EOI)")
        return

    frame = response[1:-1].decode("ascii", errors="replace")
    if len(frame) < 16:
        print("frame too short")
        return

    received_checksum = frame[-4:]
    body = frame[:-4]
    expected_checksum = pylon_ascii_checksum(body)
    if received_checksum != expected_checksum:
        print(f"checksum mismatch: received={received_checksum} expected={expected_checksum}")
        return

    ver = body[0:2]
    adr = int(body[2:4], 16)
    cid1 = body[4:6]
    rtn = int(body[6:8], 16)
    length_hex = body[8:12]
    lenid = int(length_hex, 16) & 0x0FFF
    info_hex = body[12:12 + lenid]

    print(f"VER={ver} ADR=0x{adr:02X} CID1={cid1} RTN=0x{rtn:02X} ({PYLON_RESPONSE_CODES.get(rtn, 'unknown')}) LENID={lenid}")

    if rtn != PYLON_RESPONSE_OK:
        print("battery returned an error response, see RTN code above")
        return

    if len(info_hex) < 22:
        print(f"INFO shorter than expected ({len(info_hex)} hex chars), raw: {info_hex}")
        return

    parsed = parse_pylon_system_analog(info_hex)
    print("Parsed:", parsed)


def main():
    ser = serial.Serial(port=PYLON_PORT, baudrate=PYLON_BAUD, timeout=PYLON_TIMEOUT_SECONDS)
    print(f"opened {PYLON_PORT} at {PYLON_BAUD} baud, querying ADR=0x{PYLON_ADR:02X} every 5s, Ctrl+C to stop")
    while True:
        query_system_analog(ser)
        print("---")
        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
