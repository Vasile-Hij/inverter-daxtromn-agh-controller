# Solar Monitor

Raspberry Pi 4 controller for a Daxtromn AGH 10.2kW inverter (2 MPPT), DAH 16S LiFePO4 battery 14.8kw, ZMAi-90 grid meter ([reflashed](https://www.elektroda.com/rtvforum/topic4014818.html) from Tuya to OpenBeken) and N-PE bonding relay. Publishes everything to Home Assistant via MQTT, but it can work standalone as well.

## Known issues

- **PV2 not reported** by the inverter; derived: `(ac_output - grid) / efficiency - battery - pv1`.
- **N-PE leak** when islanding (decocted from grid despite it reads grid voltage); SSR (contactor  with heat sink is preferred instead of a relay) bonds N-PE only when off-grid (ZMAi-90 + inverter, 3s delay). If bonding is missing when inverter is not consuming energy from grid (off-grid or islanding), it leaks 90V on N wire being a fire hazards and damaging electrical/electronic devices. Warning: in TN-C-S system it is forbidden to wire N to PE while linked to grid!

## Hardware

It can work with or without Home Assistant! Some fields can be changed from HA: charging battery mode: auto (solar priority), manual (charge from grid in case a grid surge is scheduled and sun it is not enough to charge battery in full). Also options for battery voltage or percentage of battery multiple-thresholds. 

| Device | Setup |
|---|---|
| Raspberry-pi 4B | Works standalone or with HA |
| Daxtromn inverter AGH 10.2kw | RS232 (PI30), FTDI USB to raspberry |
| DAH battery | CAN 500kbps (MCP2515), battery port `CAN` |
| Inverter ↔ battery | RS485 RJ45, battery port `485` (program 05 = LIC/LIP) |
| ZMAi-90 meter | MQTT (reflashed from Tuya to OpenBeken) |
| N-PE SSR 25A | Relay 25A + GPIO 27 |

## Battery strategy

Program 01 = **SBU**, set on the LCD (firmware NAKs POP02 over serial; the Pi never sends POP).

| State | When | 16 (charger) |
|---|---|---|
| Normal | default | 050 solar only |
| Low battery | SOC ≤ 10% until 30% | C50 solar first |
| No battery | BMS cut off for 60s | SNU solar + grid |
| Quick charge | manual, until 90% | SNU, then 050 |
| BMS offline fallback | no BMS + no solar 3h | SNU |

Programs 12/13 (back to grid / back to battery): 49.0V / 52.0V. In SBU the inverter moves the load to grid below 49V (battery dies ~46V).
Low battery raises them to 51.0V / 58.0V (both maximums): the load goes to grid once the battery is at or below 51V, and stays there until Grid Stop Charging SOC, when the HA values return.

All thresholds are HA numbers (retained MQTT + `soc_settings.json`). Every inverter setting is read back after sending and re-checked every 10 min.

## Known issues

- **PV2 not reported** by the inverter; derived: `(ac_output - grid) / efficiency - battery - pv1`.
- **N-PE leak** when islanding; SSR bonds N-PE only when off-grid (ZMAi-90 + inverter, 3s delay).

## Setup

```bash
uv venv && source .venv/bin/activate && uv pip install -e .
sudo bash setup_can.sh && sudo reboot
```

`.env`:
```
MQTT_HOST=127.0.0.1
MQTT_PORT=1883
MQTT_USER=mqtt-rasp
MQTT_PASSWORD=<password>
```

MCP2515 wiring: VCC 5V, GND, CS GPIO8, MOSI GPIO10, MISO GPIO9, SCK GPIO11, INT GPIO25; CAN_H RJ45 pin 4, CAN_L pin 5, 120Ω terminator.

## CAN

Check: `candump can0` (expect 0x351, 0x355, 0x356, 0x359, 0x35C, 0x35E, 0x373, 0x379).

Auto-recover from BUS-OFF (already in `setup_can.sh`; for an existing install):
```bash
sudo sed -i "s/bitrate 500000$/bitrate 500000 restart-ms 100/" /etc/systemd/system/can0.service && sudo systemctl daemon-reload
```

Recover a stuck bus now:
```bash
sudo ip link set can0 down && sudo ip link set can0 type can bitrate 500000 restart-ms 100 && sudo ip link set can0 up
```

## Service

```bash
sudo systemctl {start|stop|restart|status} solar-monitor
journalctl -u solar-monitor -f
cd /home/vhij/ctrl && ./bin/pytest tests/ -q
```

The service restarts itself when a source file changes.
