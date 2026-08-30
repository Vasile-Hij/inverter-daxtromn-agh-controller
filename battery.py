"""Battery domain helpers: SOC estimation from LiFePO4 open-circuit voltage."""

# 16S LiFePO4 OCV-to-SOC lookup (voltage_v, soc_pct)
LIFEPO4_16S_SOC_TABLE = [
    (44.0, 0),
    (49.6, 10),
    (51.2, 20),
    (52.0, 30),
    (52.4, 40),
    (52.6, 50),
    (52.8, 60),
    (53.0, 70),
    (53.3, 80),
    (53.6, 90),
    (54.4, 95),
    (58.4, 100),
]


def estimate_soc_from_voltage(voltage_v):
    table = LIFEPO4_16S_SOC_TABLE
    if voltage_v <= table[0][0]:
        return table[0][1]
    if voltage_v >= table[-1][0]:
        return table[-1][1]
    for index in range(1, len(table)):
        if voltage_v <= table[index][0]:
            low_voltage, low_soc = table[index - 1]
            high_voltage, high_soc = table[index]
            fraction = (voltage_v - low_voltage) / (high_voltage - low_voltage)
            return round(low_soc + fraction * (high_soc - low_soc))
    return table[-1][1]
