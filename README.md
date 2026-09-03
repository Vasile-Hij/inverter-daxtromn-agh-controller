# Summary
Control Daxtromn 10.2kw AGH inverter with 2 MPPT and DAH battery. Added N-PE bonding relay control as Daxtromn is missing feature and fire hazard (flowing 90V on N wire when inverter is not using grid) and calculate missing 2nd PV from MPPT data with and without battery.

# Issues with Daxtromn 10.2kw AGH version
- DessMonitor app does not display PV2 for Daxtromn AGH 10.2kw version, just PV1 and total consumption and some settings; Formula I have found in several tests is: pv2 = (ac_output - grid_power) / efficiency - battery_net - pv1.
	Where:
	- ac_output = ac_output_power_w (inverter QPIGS)
	- grid_power = ZMAi-90 meter reading (W)
	- efficiency = 0.93 (DC-AC conversion loss, configurable via MQTT)
	- battery_net = (discharge_current - charge_current) * battery_voltage (0 when no battery detected)
	- pv1 = pv1_power_w (inverter QPIGS)
 
- Second issue I have found out about this inverter it is that sometimes 20 to 90V are leaking via NULL wire and low powered LED are blinking in complete darkness; solution tested initially it was with AC relay with NO, but that one was detecting 2-3w consumption and not activating the relay (inverter still read grid voltage despite it is full on battery + PVs in SBU (Solar, Battery, Utility-Grid)); so in TN-C-S system it is forbidden to bond NULL to PE when inverter it is connected to the grid. As the inverter it is disconnecting itself from grid when full on battery and PVs, Smart Meter Zmai-90 (deleted from Tuya and flashed with OpenBeken) it will provide the power consumption. If the consumption is in acceptable range 30-120-150w means "no grid consumption", just power itself and it is "islanding" providing power to house from PVs and battery, so in this case SSR (contactor 25A) it will be activated from raspberry to draw the power from NULL to PE wire. From ZMAI-90 readings, most of the time inverter takes only 2-3w when islanding, but probably in a future update, when power it is under 150w, to shut down the ZMAI-90 (grid) and 100% being secured for bonding N to PE. For now, the reading of battery capacity via RS485 to Raspberry Pi is not working (probably need CAN cable) and inverter do not provide this information (yet).
- Third issue with inverter Daxtromn is when is in "SBU" mode on setting 02 (Solar, Battery, Utility) and "050" mode on setting 16 (means the battery it will be charging from solar only), so if 1-2-3 cloudy days with great consumption, the battery will go nealy 0% capacity and needs few manual restarts. For now I can use utility grid anytime due price is the same, if contract it will change into future with new logic (on cloudy day charging during daylight from utility and discarge battery at night, still cheaper). 

# Solar Monitor

Raspberry Pi-based solar monitoring and N-PE bonding SSR controller for a Daxtromn AGH-10.2kW hybrid inverter.

## Prerequisites

- Reads inverter data over RS232 (PI30 protocol, QPIGS) every 5 seconds
- Receives grid power/voltage/current from a ZMAi-90 smart meter over MQTT
- Derives PV2 power from energy balance (the firmware does not expose PV2 via serial)
- Auto-detects battery presence from 5 independent inverter signals
- Reads DAH battery BMS data over CAN bus (SOC, cell voltages, temperatures, alarms)
- Controls an N-PE bonding relay (GPIO 27) for off-grid safety
- Publishes all data to Home Assistant via MQTT discovery

## Hardware

- Raspberry Pi 4
- Daxtromn AGH-10.2kW hybrid inverter (RS232 via Pylon cable)
- ZMAi-90 grid meter (deleted from Tuya flashed with BK7231N)
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

### PV2 (derived)

The Daxtromn AGH firmware does not expose PV2 via serial. PV2 is derived from energy balance:

`pv2 = (ac_output / efficiency) - battery_net - pv1`

When grid meter data is available: `pv_total = (ac_output - grid_power) / efficiency - battery_net`, then `pv2 = pv_total - pv1`. Falls back to a configurable PV2/PV1 ratio (default 0.37) when the balance estimate is below PV1.

### Discharge Guard

Prevents full battery discharge in SBU mode with solar-only charging:

| Event | Action |
|-------|--------|
| SOC drops to 7% | Switches output priority to SUB (POP01) — grid powers loads, solar charges battery |
| SOC reaches 50% AND total PV > 200W | Switches back to SBU (POP02) — battery resumes powering loads |

Controllable via MQTT select entity (auto / force_sbu / force_sub).

### N-PE Bonding

SSR relay on GPIO 27 bonds neutral to protective earth when the inverter is islanding (off-grid). Triggers based on AC input voltage, grid meter power, and battery failsafe signals with a 3-second stability delay. Disabled when battery voltage is low.

## Files

| File | Description |
|------|-------------|
| `solar_monitor.py` | Main service loop: ties meter, inverter, CAN battery, N-PE bonding, and MQTT together |
| `settings.py` | Constants, safety thresholds, MQTT topics, and env credentials |
| `home_assistant.py` | Home Assistant MQTT discovery (all sensor/select/number entities) |
| `inverter.py` | Daxtromn inverter: QPIGS polling, priority commands, battery detection |
| `can_battery.py` | CAN bus battery reader: socketCAN background thread, data access |
| `dah_can_protocol.py` | DAH battery CAN frame decoders (SMA/Pylontech-compatible protocol) |
| `battery.py` | Battery SOC estimation from LiFePO4 open-circuit voltage |
| `npe_bonding.py` | N-PE bonding relay decision logic and GPIO control |
| `zmai_meter.py` | ZMAi-90 grid meter state fed by MQTT pushes |
| `discharge_guard.py` | Switches output priority to protect the battery at low SOC |
| `alarm.py` | Fault logging with slow repeat while a fault persists |
| `daxtromn_config.py` | CLI tool to read/write inverter battery settings (QPIRI) |
| `pylon_battery_test.py` | Diagnostic tool: query Pylon battery system analog data |
| `pylon_scan.py` | Scan for Pylon batteries across baud rates and addresses |
| `tomzn_pulse.py` | Diagnostic tool: read Tomzn meter pulse output on GPIO17 |
| `pi30.py` | Base class for PI30 protocol serial communication |
| `pylon.py` | Base class for Pylon battery protocol communication |
| `setup_can.sh` | One-time setup: enables SPI, MCP2515 overlay, and can0 systemd service |

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
