# Issues with Daxtromn 10.2kw
- DessMonitor app does not display PV2 for Daxtromn AGH 10.2kw version, just PV1 and total consumption and some settings; Formula I have found in several tests is: pv2 = (ac_output - grid_power) / efficiency - battery_net - pv1.
	Where:
	- ac_output = ac_output_power_w (inverter QPIGS)
	- grid_power = ZMAi-90 meter reading (W)
	- efficiency = 0.93 (DC-AC conversion loss, configurable via MQTT)
	- battery_net = (discharge_current - charge_current) * battery_voltage (0 when no battery detected)
	- pv1 = pv1_power_w (inverter QPIGS)
 
- Second issue I have found out about this inverter it is that sometimes 20 to 90V are leaking via NULL wire and low powered LED are blinking in complete darkness; solution tested initially it was with AC relay with NO, but that one was detecting 2-3w consumption and not activating the relay (inverter still read grid voltage despite it is full on battery + PVs in SBU (Solar, Battery, Utility-Grid)); so in TN-C-S system it is forbidden to bond NULL to PE when inverter it is connected to the grid. As the inverter it is disconnecting itself from grid when full on battery and PVs, Smart Meter Zmai-90 (deleted from Tuya and flashed with OpenBeken) it will provide the power consumption. If the consumption is in acceptable range 30-120-150w means "no grid consumption", just power itself and it is "islanding" providing power to house from PVs and battery, so in this case SSR (contactor 25A) it will be activated from raspberry to draw the power from NULL to PE wire. From ZMAI-90 readings, most of the time inverter takes only 2-3w when islanding, but probably in a future update, when power it is under 150w, to shut down the ZMAI-90 (grid) and 100% being secured for bonding N to PE. For now, the reading of battery capacity via RS485 to Raspberry Pi is not working (probably need CAN cable) and inverter do not provide this information (yet).


# Solar Monitor

Raspberry Pi-based solar monitoring and N-PE bonding SSR controller for a Daxtromn AGH-10.2kW hybrid inverter.

## Prerequisites

- Reads inverter data over RS232 (PI30 protocol, QPIGS) every 5 seconds
- Receives grid power/voltage/current from a ZMAi-90 smart meter over MQTT
- Derives PV2 power from energy balance (the firmware does not expose PV2 via serial)
- Auto-detects battery presence from 5 independent inverter signals
- Controls an N-PE bonding relay (GPIO 27) for off-grid safety
- Publishes all data to Home Assistant via MQTT discovery

## Hardware

- Raspberry Pi 4
- Daxtromn AGH-10.2kW hybrid inverter (RS232 via Pylon cable)
- ZMAi-90 grid meter (deleted from Tuya flashed with BK7231N)
- N-PE bonding SSR 25A on GPIO 27
- Optional: DAH LiFePO4 battery (communicates with inverter via CAN or takes partial data from inverter)

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
uv pip install paho-mqtt pyserial gpiozero
```

Create a `.env` file with MQTT credentials:

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
source bin/activate
source .env && export MQTT_HOST MQTT_PORT MQTT_USER MQTT_PASSWORD
python3 solar_monitor.py
```

Configure inverter battery settings:

```bash
python3 daxtromn_config.py
python3 daxtromn_config.py --battery-type 3 --cv-voltage 57.6
```
