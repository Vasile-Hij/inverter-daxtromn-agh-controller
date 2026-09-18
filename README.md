# Summary
Control Daxtromn 10.2kW AGH inverter with 2 MPPT and DAH battery.

# Known Issues

1. **PV2 not exposed** — DessMonitor and serial (QPIGS) only report PV1. PV2 is derived from energy balance:
   `pv2 = (ac_output - grid_power) / efficiency - battery_net - pv1`
   (efficiency default 0.93, configurable via MQTT; falls back to PV2/PV1 ratio when grid data unavailable)

2. **N-PE voltage leak** — 20–90V leak on neutral when inverter is islanding; low-powered LEDs blink in darkness. Solution: SSR relay (25A) bonds N to PE only when inverter is confirmed off-grid via ZMAi-90 power readings, with a stability delay. Forbidden when grid is connected (TN-C-S).

3. **SBU deep discharge** — In SBU mode with solar-only charging (setting 02 + setting 16 at 050), consecutive cloudy days can drain the battery near 0% requiring manual restart. Discharge Guard handles this automatically (see below).

## Prerequisites

- Reads inverter data over RS232 (PI30 protocol, QPIGS) every 5 seconds
- Receives grid power/voltage/current from a ZMAi-90 smart meter over MQTT
- Derives PV2 power from energy balance (see issue 1)
- Auto-detects battery presence from 5 independent inverter signals
- Reads DAH battery BMS data over CAN bus (SOC, cell voltages, temperatures, alarms)
- Controls an N-PE bonding relay on GPIO 27 (see issue 2)
- Publishes all data to Home Assistant via MQTT discovery

## Hardware

- Raspberry Pi 4
- Daxtromn AGH-10.2kW hybrid inverter (RS232 via Pylon cable)
- ZMAi-90 grid meter (flashed with OpenBeken BK7231N)
- N-PE bonding SSR 25A on GPIO 27
- DAH LiFePO4 16S battery (CAN bus via MCP2515 module)

## Output

### Inverter (QPIGS)

AC input/output voltage, frequency, power, load %; bus voltage; PV1 voltage, current, power; heatsink temperature; device status bits.

### Battery (CAN bus)

| Metric | Source | CAN ID |
|--------|--------|--------|
| SOC (%) | BMS direct | 0x355 |
| SOH (%) | BMS direct | 0x355 |
| Pack voltage (V) | BMS direct | 0x356 |
| Pack current (A) | BMS direct | 0x356 |
| Pack temperature (C) | BMS direct | 0x356 |
| Cell min/max voltage (mV) | BMS direct | 0x373 |
| Cell voltage diff (mV) | Derived from 0x373 | 0x373 |
| Cell temp min/max (C) | BMS direct | 0x373 |
| Charge/discharge limits | BMS direct | 0x351 |
| Alarms and warnings | BMS direct | 0x359 |
| Charge/discharge enable | BMS direct | 0x35C |
| Capacity (Ah) | BMS direct | 0x379 |
| Manufacturer | BMS direct | 0x35E |

### Battery (inverter-derived, fallback)

| Metric | Source |
|--------|--------|
| Voltage, charge/discharge current | Inverter QPIGS |
| Power (W) | `(discharge_A - charge_A) * voltage_V` |
| SOC (estimated %) | Voltage-based lookup table (16S LiFePO4 OCV curve, 44.0V=0% to 58.4V=100%) |
| Capacity (%) | Inverter QPIGS `battery_capacity_pct` (voltage-based, no BMS comms) |
| Charge/discharge energy (kWh) | Accumulated from power over time |
| Low voltage alert | Triggered when voltage < 44.0V |

### Discharge Guard

Prevents full battery discharge in SBU mode with solar-only charging (see issue 3):

| Event | Action |
|-------|--------|
| SOC drops to 7% | Switches output priority to SUB (POP01) — grid powers loads, solar charges battery |
| SOC reaches 50% AND total PV > 200W | Switches back to SBU (POP02) — battery resumes powering loads |

Controllable via MQTT select entity (auto / force_sbu / force_sub).

### N-PE Bonding

SSR relay on GPIO 27 bonds neutral to protective earth when the inverter is islanding (see issue 2). Triggers based on AC input voltage, grid meter power, and battery failsafe signals with a 3-second stability delay. Disabled when battery voltage is low.

## Setup

### 1. Install dependencies with uv

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

### 2. CAN bus hardware (MCP2515)

#### Wiring

```
MCP2515 → Pi GPIO          MCP2515 → Battery RJ45
VCC  → 5V (pin 2)          CAN_H → Pin 4
GND  → GND (pin 6)         CAN_L → Pin 5
CS   → GPIO 8 / CE0 (pin 24)
MOSI → GPIO 10 (pin 19)    120Ω terminator between CAN_H and CAN_L
MISO → GPIO 9 (pin 21)
SCK  → GPIO 11 (pin 23)
INT  → GPIO 25 (pin 22)
```

#### Enable SPI and MCP2515 overlay

Run the setup script (enables SPI, adds dtoverlay, creates can0 systemd service):

```bash
sudo bash setup_can.sh
sudo reboot
```

After reboot, verify CAN bus:

```bash
sudo apt install can-utils
candump can0
```

You should see frames from the DAH battery (0x351, 0x355, 0x356, 0x359, 0x35C, 0x35E, 0x373, 0x379).

#### Manual setup (alternative)

Edit `/boot/firmware/config.txt`:

```
# Uncomment in the hardware interfaces section:
dtparam=spi=on

# Add under [all]:
dtoverlay=mcp2515-can0,oscillator=8000000,interrupt=25,spimaxfrequency=1000000
```

Bring up can0 manually:

```bash
sudo ip link set can0 up type can bitrate 500000
```

### 3. MQTT credentials

Create a `.env` file:

```
MQTT_HOST=127.0.0.1
MQTT_PORT=1883
MQTT_USER=mqtt-rasp
MQTT_PASSWORD=<password>
```

## Service

Start, stop, and check the systemd service:

```bash
sudo systemctl start solar-monitor
sudo systemctl stop solar-monitor
sudo systemctl restart solar-monitor
sudo systemctl status solar-monitor
```

View live logs:

```bash
journalctl -u solar-monitor -f
```

Enable on boot:

```bash
sudo systemctl enable solar-monitor
```

## Usage

Run manually (outside systemd):

```bash
source .venv/bin/activate
source .env && export MQTT_HOST MQTT_PORT MQTT_USER MQTT_PASSWORD
python3 solar_monitor.py
```

Configure inverter battery settings:

```bash
python3 daxtromn_config.py
python3 daxtromn_config.py --battery-type 3 --cv-voltage 57.6
```

## DAH CAN Protocol

The DAH battery uses an SMA/Pylontech-compatible CAN protocol at 500kbps. Frame decoders are in `dah_can_protocol.py`.

| CAN ID | Description | Data |
|--------|-------------|------|
| 0x351 | Charge/discharge limits | charge_voltage (0.1V), charge_current (0.1A), discharge_current (0.1A), discharge_voltage (0.1V) |
| 0x355 | State of charge/health | SOC (%), SOH (%) |
| 0x356 | Pack measurements | voltage (0.01V), current (0.1A), temperature (0.1C) |
| 0x359 | Alarms and warnings | alarm flags, warning flags, module count |
| 0x35C | Charge request | charge_enable, discharge_enable, force_charge_request |
| 0x35E | Manufacturer | ASCII string ("DAH") |
| 0x373 | Cell min/max | cell_min_mv, cell_max_mv, temp_min (0.1C), temp_max (0.1C) |
| 0x379 | Capacity | capacity_ah |
