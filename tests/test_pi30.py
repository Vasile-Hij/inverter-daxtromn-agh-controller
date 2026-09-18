from inverter.pi30 import is_number, PI30Connection


class TestIsNumber:

    def test_positive_integer(self):
        assert is_number("42") is True

    def test_negative_integer(self):
        assert is_number("-7") is True

    def test_float(self):
        assert is_number("3.14") is True

    def test_negative_float(self):
        assert is_number("-0.5") is True

    def test_zero(self):
        assert is_number("0") is True

    def test_empty_string(self):
        assert is_number("") is False

    def test_whitespace_only(self):
        assert is_number("   ") is False

    def test_text(self):
        assert is_number("abc") is False

    def test_mixed(self):
        assert is_number("12abc") is False

    def test_with_leading_whitespace(self):
        assert is_number("  230.5  ") is True

    def test_with_plus_sign(self):
        assert is_number("+10") is True

    def test_double_dot(self):
        assert is_number("1.2.3") is False


class TestPI30Crc:

    def test_qpigs_crc(self):
        crc = PI30Connection.compute_crc(b"QPIGS")
        high = (crc >> 8) & 0xFF
        low = crc & 0xFF
        assert bytes([high, low]) == b"\xb7\xa9"

    def test_build_command_ends_with_cr(self):
        command = PI30Connection.build_command("QPIGS")
        assert command.endswith(b"\r")
        assert command.startswith(b"QPIGS")

    def test_build_command_contains_crc(self):
        command = PI30Connection.build_command("QPIGS")
        assert b"\xb7\xa9" in command


class TestExtractPayload:

    def test_valid_response(self):
        response = b"(230.0 50.0 some data XX\r"
        payload = PI30Connection.extract_payload(response)
        assert payload is not None
        assert "230.0" in payload

    def test_none_response(self):
        assert PI30Connection.extract_payload(None) is None

    def test_no_opening_paren(self):
        assert PI30Connection.extract_payload(b"no paren here\r") is None

    def test_strips_crc_bytes(self):
        response = b"(ABCXY\r"
        payload = PI30Connection.extract_payload(response)
        assert payload == "ABC"
