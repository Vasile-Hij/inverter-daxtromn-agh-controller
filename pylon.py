import serial


class PylonConnection:
    """Pylon battery protocol communication over RS485.

    Provides ASCII checksum, query building, connection management, and frame
    parsing shared by all Pylon-protocol tools (monitor, scanner).
    """

    CID1 = 0x46
    RESPONSE_OK = 0x00
    RESPONSE_CODES = {
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

    def __init__(self, port, baud, address, timeout=2):
        self._port = port
        self._baud = baud
        self._address = address
        self._timeout = timeout
        self._connection = None

    @staticmethod
    def ascii_checksum(payload):
        total = sum(ord(char) for char in payload) % 65536
        return f"{(~total + 1) & 0xFFFF:04X}"

    def build_query(self, cid2, address=None):
        if address is None:
            address = self._address
        body = f"20{address:02X}{self.CID1:02X}{cid2:02X}0000"
        frame = "~" + body + self.ascii_checksum(body) + "\r"
        return frame.encode("ascii")

    def open(self):
        self._connection = serial.Serial(
            port=self._port, baudrate=self._baud, timeout=self._timeout
        )

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def send_query(self, cid2):
        self._connection.reset_input_buffer()
        command = self.build_query(cid2)
        self._connection.write(command)
        return self._connection.read_until(b"\r")

    def parse_frame(self, response):
        if not response:
            return None
        if not response.startswith(b"~") or not response.endswith(b"\r"):
            return None
        frame = response[1:-1].decode("ascii", errors="replace")
        if len(frame) < 16:
            return None
        received_checksum = frame[-4:]
        body = frame[:-4]
        expected_checksum = self.ascii_checksum(body)
        if received_checksum != expected_checksum:
            return None
        version = body[0:2]
        address = int(body[2:4], 16)
        cid1 = body[4:6]
        return_code = int(body[6:8], 16)
        length_hex = body[8:12]
        lenid = int(length_hex, 16) & 0x0FFF
        info_hex = body[12 : 12 + lenid]
        return {
            "version": version,
            "address": address,
            "cid1": cid1,
            "return_code": return_code,
            "lenid": lenid,
            "info_hex": info_hex,
        }
