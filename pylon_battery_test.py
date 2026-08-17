import sys
import time

from pylon import PylonConnection

PYLON_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
PYLON_BAUD = 9600
PYLON_ADDRESS = 0x02
PYLON_TIMEOUT_SECONDS = 2


class PylonMonitor(PylonConnection):
    """Continuously queries a Pylon battery for system analog data.

    Extends PylonConnection with system-analog parsing and verbose diagnostic
    output for debugging wiring, polarity, and protocol issues.
    """

    CID2_ANALOG = 0x42
    CID2_SYSTEM_ANALOG = 0x61

    def __init__(self, port, baud, address, timeout=2):
        super().__init__(port, baud, address, timeout)

    @staticmethod
    def parse_system_analog(info_hex):
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

    def query_system_analog(self):
        command = self.build_query(self.CID2_SYSTEM_ANALOG)
        print("TX:", command)

        response = self.send_query(self.CID2_SYSTEM_ANALOG)
        print("RX:", response)

        if not response:
            print("no response (timeout) -- check wiring, A/B polarity, baud rate, and address")
            return

        parsed = self.parse_frame(response)
        if parsed is None:
            print("malformed or invalid frame")
            return

        return_code = parsed["return_code"]
        info_hex = parsed["info_hex"]
        print(
            f"VER={parsed['version']} ADR=0x{parsed['address']:02X} "
            f"CID1={parsed['cid1']} RTN=0x{return_code:02X} "
            f"({self.RESPONSE_CODES.get(return_code, 'unknown')}) "
            f"LENID={parsed['lenid']}"
        )

        if return_code != self.RESPONSE_OK:
            print("battery returned an error response, see RTN code above")
            return

        if len(info_hex) < 22:
            print(f"INFO shorter than expected ({len(info_hex)} hex chars), raw: {info_hex}")
            return

        data = self.parse_system_analog(info_hex)
        print("Parsed:", data)

    def run(self):
        self.open()
        print(f"opened {self._port} at {self._baud} baud, querying ADR=0x{self._address:02X} every 5s, Ctrl+C to stop")
        while True:
            self.query_system_analog()
            print("---")
            time.sleep(5)


def main():
    monitor = PylonMonitor(PYLON_PORT, PYLON_BAUD, PYLON_ADDRESS, PYLON_TIMEOUT_SECONDS)
    monitor.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
