import os
import time

import serial

CRC_RESERVED_BYTES = (0x28, 0x0D, 0x0A)


def is_number(text):
    stripped = text.strip()
    if not stripped:
        return False
    return stripped.lstrip("-+").replace(".", "", 1).isdigit()


class PI30Connection:
    """PI30 protocol communication over RS232.

    Provides CRC calculation, command building, and serial I/O shared by all
    PI30-speaking devices (inverter polling, configuration tool).
    """

    def __init__(self, port, baud):
        self._port = port
        self._baud = baud

    @staticmethod
    def compute_crc(data):
        crc = 0
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021
                else:
                    crc <<= 1
                crc &= 0xFFFF
        return crc

    @classmethod
    def build_command(cls, command_text):
        command_bytes = command_text.encode("ascii")
        crc = cls.compute_crc(command_bytes)
        crc_bytes = [cls._escape_crc_byte((crc >> 8) & 0xFF), cls._escape_crc_byte(crc & 0xFF)]
        return command_bytes + bytes(crc_bytes) + b"\r"

    @staticmethod
    def _escape_crc_byte(crc_byte):
        # PI30: a CRC byte equal to "(", CR or LF would cut the frame short (POP02 ends in LF), so it is sent +1
        if crc_byte in CRC_RESERVED_BYTES:
            return crc_byte + 1
        return crc_byte

    def send_raw_command(self, raw_command):
        if not os.path.exists(self._port):
            return None
        connection = serial.Serial(self._port, self._baud, timeout=2)
        connection.reset_input_buffer()
        connection.write(raw_command)
        raw_response = b""
        read_deadline = time.time() + 2
        while time.time() < read_deadline:
            waiting = connection.in_waiting
            if waiting > 0:
                raw_response += connection.read(waiting)
            else:
                incoming_byte = connection.read(1)
                if not incoming_byte:
                    break
                raw_response += incoming_byte
        connection.reset_input_buffer()
        connection.close()
        return raw_response

    def send_command(self, command_text):
        return self.send_raw_command(self.build_command(command_text))

    @staticmethod
    def extract_payload(raw_response):
        if raw_response is None:
            return None
        frame_start = raw_response.find(b"(")
        if frame_start < 0:
            return None
        frame_end = raw_response.find(b"\r", frame_start)
        if frame_end < 0:
            frame_end = len(raw_response)
        payload_with_crc = raw_response[frame_start + 1 : frame_end]
        if len(payload_with_crc) >= 2:
            return payload_with_crc[:-2].decode("ascii", errors="replace")
        return payload_with_crc.decode("ascii", errors="replace")
