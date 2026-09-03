"""CAN bus battery reader: reads BMS frames from socketCAN on a background thread.

Protocol decoding is in dah_can_protocol.py.  This module handles the socket
lifecycle, threading, and data access for the main polling loop.
"""

import socket
import struct
import threading
import time

from dah_can_protocol import FRAME_DECODERS


CAN_FRAME_FORMAT = "=IB3x8s"
CAN_FRAME_SIZE = struct.calcsize(CAN_FRAME_FORMAT)
CAN_ID_MASK = 0x1FFFFFFF


class CanBattery:
    """Non-blocking CAN bus battery reader running on a background thread."""

    def __init__(self, interface, stale_seconds):
        self._interface = interface
        self._stale_seconds = stale_seconds
        self._lock = threading.Lock()
        self._fields = {}
        self._last_frame_time = None
        self._seen_unknown_ids = set()
        self._socket = None
        self._thread = None
        self._running = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._socket is not None:
            self._socket.close()

    def _open_socket(self):
        sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        sock.bind((self._interface,))
        sock.settimeout(2.0)
        return sock

    def _read_loop(self):
        while self._running:
            if self._socket is None:
                if not self._try_connect():
                    time.sleep(5)
                    continue
            if not self._read_one_frame():
                self._socket = None

    def _try_connect(self):
        try:
            self._socket = self._open_socket()
            print(f"can_battery: connected to {self._interface}", flush=True)
            return True
        except OSError as error:
            print(f"can_battery: {self._interface} not available ({error}), retrying in 5s", flush=True)
            return False

    def _read_one_frame(self):
        try:
            raw_frame = self._socket.recv(CAN_FRAME_SIZE)
        except socket.timeout:
            return True
        except OSError:
            return False

        if len(raw_frame) < CAN_FRAME_SIZE:
            return True

        raw_can_id, data_length, data = struct.unpack(CAN_FRAME_FORMAT, raw_frame)
        can_id = raw_can_id & CAN_ID_MASK
        payload = data[:data_length]

        decoder = FRAME_DECODERS.get(can_id)
        if decoder is not None:
            with self._lock:
                decoder(payload, self._fields)
                self._last_frame_time = time.time()
        elif can_id not in self._seen_unknown_ids:
            self._seen_unknown_ids.add(can_id)
            hex_payload = payload.hex()
            print(f"can_battery: unknown CAN ID 0x{can_id:03X} len={data_length} data={hex_payload}", flush=True)

        return True

    def get_data(self):
        with self._lock:
            if not self._fields:
                return None
            return dict(self._fields)

    def has_recent_data(self, now):
        with self._lock:
            if self._last_frame_time is None:
                return False
            return (now - self._last_frame_time) < self._stale_seconds

    def is_online(self):
        return self._socket is not None and self._running
