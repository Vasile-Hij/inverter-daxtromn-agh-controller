from batteries.battery import estimate_soc_from_voltage, LIFEPO4_16S_SOC_TABLE


class TestEstimateSocFromVoltage:

    def test_below_minimum_returns_zero(self):
        assert estimate_soc_from_voltage(40.0) == 0

    def test_at_minimum_returns_zero(self):
        assert estimate_soc_from_voltage(44.0) == 0

    def test_above_maximum_returns_hundred(self):
        assert estimate_soc_from_voltage(60.0) == 100

    def test_at_maximum_returns_hundred(self):
        assert estimate_soc_from_voltage(58.4) == 100

    def test_exact_table_entry(self):
        assert estimate_soc_from_voltage(52.0) == 30

    def test_interpolation_midpoint(self):
        result = estimate_soc_from_voltage(50.4)
        assert 10 < result < 20

    def test_all_table_entries_return_exact_soc(self):
        for voltage, expected_soc in LIFEPO4_16S_SOC_TABLE:
            assert estimate_soc_from_voltage(voltage) == expected_soc

    def test_monotonically_increasing(self):
        voltages = [44.0 + i * 0.5 for i in range(30)]
        soc_values = [estimate_soc_from_voltage(v) for v in voltages]
        for index in range(1, len(soc_values)):
            assert soc_values[index] >= soc_values[index - 1]
