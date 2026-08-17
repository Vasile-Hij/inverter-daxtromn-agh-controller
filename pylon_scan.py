"""Scan for a Pylon-compatible battery across baud rates and addresses."""

import sys
import serial

PYLON_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
PYLON_CID1 = 0x46
PYLON_CID2_SYSTEM_ANALOG = 0x61
BAUD_RATES = [115200, 9600, 19200, 2400, 4800, 38400, 57600]
ADDRESSES = [0x02, 0x12, 0x01, 0x22, 0x00, 0x03, 0x04, 0x32, 0x42]


def pylon_ascii_checksum(payload):
    total = sum(ord(char) for char in payload) % 65536
    return f"{(~total + 1) & 0xFFFF:04X}"


def build_pylon_query(adr, cid2):
    body = f"20{adr:02X}{PYLON_CID1:02X}{cid2:02X}0000"
    frame = "~" + body + pylon_ascii_checksum(body) + "\r"
    return frame.encode("ascii")


def scan():
    for baud in BAUD_RATES:
        print(f"\n=== Baud rate: {baud} ===")
        for adr in ADDRESSES:
            command = build_pylon_query(adr, PYLON_CID2_SYSTEM_ANALOG)
            connection = serial.Serial(PYLON_PORT, baud, timeout=1)
            connection.reset_input_buffer()
            connection.write(command)

            response = connection.read_until(b"\r")
            connection.close()

            if response:
                print(f"  ADR=0x{adr:02X}: RESPONSE! {response}")
            else:
                print(f"  ADR=0x{adr:02X}: no response")


if __name__ == "__main__":
    scan()
