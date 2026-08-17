# Solar Monitor

Raspberry Pi-based solar monitoring and N-PE bonding controller for a Daxtromn AGH-10.2kW hybrid inverter.

## What it does

- Reads inverter data over RS232 (PI30 protocol, QPIGS) every 5 seconds
- Receives grid power/voltage/current from a ZMAi-90 smart meter over MQTT
- Derives PV2 power from energy balance (the firmware does not expose PV2 via serial)
- Auto-detects battery presence from 5 independent inverter signals
- Controls an N-PE bonding relay (GPIO 27) for off-grid safety
- Publishes all data to Home Assistant via MQTT discovery

## Hardware

- Raspberry Pi (any model with GPIO and USB)
- Daxtromn AGH-10.2kW hybrid inverter (RS232 via FTDI USB adapter)
- ZMAi-90 grid meter (BK7231N/CBU, OpenBeken + RN8209 driver, MQTT)
- N-PE bonding relay on GPIO 27
- Optional: DAH LiFePO4 battery (communicates with inverter via CAN)

## Files

| File | Description |
|------|-------------|
| `solar_monitor.py` | Main service: inverter polling, MQTT, N-PE bonding logic |
| `daxtromn_config.py` | CLI tool to read/write inverter battery settings (QPIRI) |
| `pylon_battery_test.py` | Diagnostic tool: query Pylon battery system analog data |
| `pylon_scan.py` | Scan for Pylon batteries across baud rates and addresses |
| `pi30.py` | Base class for PI30 protocol serial communication |
| `pylon.py` | Base class for Pylon battery protocol communication |

## Setup

```bash
python3 -m venv .
source bin/activate
pip install paho-mqtt pyserial gpiozero
```

Create a `.env` file with MQTT credentials:

```
MQTT_HOST=127.0.0.1
MQTT_PORT=1883
MQTT_USER=mqtt-rasp
MQTT_PASSWORD=<password>
```

## Usage

```bash
source bin/activate
source .env && export MQTT_HOST MQTT_PORT MQTT_USER MQTT_PASSWORD
python3 solar_monitor.py
```

Configure inverter battery settings:

```bash
python3 daxtromn_config.py
python3 daxtromn_config.py --battery-type 3 --cv-voltage 57.6
```
