"""Scan for a Pylon-compatible battery across baud rates and addresses."""

import sys

from pylon import PylonConnection

PYLON_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"


class PylonScanner(PylonConnection):
    """Scans baud rates and addresses to find a Pylon battery.

    Extends PylonConnection with multi-baud, multi-address sweep logic.
    """

    BAUD_RATES = [115200, 9600, 19200, 2400, 4800, 38400, 57600]
    SCAN_ADDRESSES = [0x02, 0x12, 0x01, 0x22, 0x00, 0x03, 0x04, 0x32, 0x42]
    CID2_SYSTEM_ANALOG = 0x61

    def __init__(self, port):
        super().__init__(port, baud=self.BAUD_RATES[0], address=self.SCAN_ADDRESSES[0], timeout=1)

    def scan(self):
        for baud in self.BAUD_RATES:
            print(f"\n=== Baud rate: {baud} ===")
            for address in self.SCAN_ADDRESSES:
                self._baud = baud
                self._address = address
                self.open()
                response = self.send_query(self.CID2_SYSTEM_ANALOG)
                self.close()

                if response:
                    print(f"  ADR=0x{address:02X}: RESPONSE! {response}")
                else:
                    print(f"  ADR=0x{address:02X}: no response")

    def run(self):
        self.scan()


def main():
    scanner = PylonScanner(PYLON_PORT)
    scanner.run()


if __name__ == "__main__":
    main()
