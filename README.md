# Solar Monitor

Raspberry Pi 4 controller for a Daxtromn AGH 10.2kW inverter (2 MPPT), DAH 16S LiFePO4 battery 14.8kw, ZMAi-90 grid meter ([reflashed](https://www.elektroda.com/rtvforum/topic4014818.html) from Tuya to OpenBeken) and N-PE bonding relay. Publishes everything to Home Assistant via MQTT, but it can work standalone as well.

## Known issues

- **PV2 not reported** by the inverter; derived from energy balance when grid is not charging the battery, or from PV1 × ratio when grid charges (balance is timing-sensitive during grid charging). See PV2 estimation below.
- **N-PE leak** when islanding (decocted from grid despite it reads grid voltage); SSR (contactor  with heat sink is preferred instead of a relay) bonds N-PE only when off-grid (ZMAi-90 + inverter, 3s delay). If bonding is missing when inverter is not consuming energy from grid (off-grid or islanding), it leaks 90V on N wire being a fire hazards and damaging electrical/electronic devices. Warning: in TN-C-S system it is forbidden to wire N to PE while linked to grid!

## Hardware

It can work with or without Home Assistant! Battery mode is picked from HA (normal, economy, quick grid, see Battery strategy); thresholds are HA numbers.

| Device | Setup |
|---|---|
| Raspberry-pi 4B | Works standalone or with HA |
| Daxtromn inverter AGH 10.2kw | RS232 (PI30), RJ45 (FTDI) USB to raspberry (need rewiring for some cables) |
| DAH battery | CAN 500kbps (MCP2515), battery port `CAN` |
| Inverter ↔ battery | RS485 RJ45, battery port `485` (program 05 = LIC/LIP) |
| ZMAi-90 meter | MQTT (reflashed from Tuya to OpenBeken) |
| N-PE SSR 25A | Relay 25A + GPIO 27 |

## Battery strategy

Battery mode (HA select) is the global trigger: each state sets program 01 (output priority), 16 (charger source),
12/13 and 11 together, and the HA boxes for 11/12/13 show what the mode runs.

| Battery mode | State | When | 01 | 16 | 12 / 13 | 11 |
|---|---|---|---|---|---|---|
| normal | house on battery | default | SBU | CSO | HA values | 2A |
| normal | house on grid, grid charging | SOC ≤ Low Battery Protection until Grid Stop Charging | SUB | CSO | 51 / 58V | HA value |
| economy | house on battery | default, or PV above house load for ~1 min | SBU | OSO | HA values | 2A |
| economy | house on grid, battery resting | SOC ≤ Low Battery Protection and PV below house load | SUB | OSO | 51 / 58V | 2A |
| quick_grid | house on grid, grid charging | SOC below Grid Quick Charge (after reaching it: 5% below) | SUB | CSO | 51 / 58V | HA value |
| quick_grid | house on battery | SOC at Grid Quick Charge | SBU | OSO | HA values | 2A |
| any | no battery | BMS cut off for 60s | SUB | OSO | 51 / 58V | 2A |
| normal, quick_grid | BMS offline fallback | no BMS + no solar 3h | SUB | CSO | 51 / 58V | HA value |

Why SUB: under SBU the inverter leaves the battery only below program 12 (51V maximum), where this LiFePO4 still rests
at ~10%, and in battery mode it never grid-charges. Why CSO: on this inverter only charger source CSO (PCP01)
grid-charges; SNU (PCP02) did not charge in two live tests. POP02 used to be NAKed because its CRC ends in 0x0A; PI30
CRC bytes 0x28/0x0D/0x0A are now sent +1, and the Pi switches SUB <-> SBU both ways.

Programs 12/13 can be changed in HA only while the house is on battery: 12 within 46-51V (above the BMS cut-off),
13 within 48-56V, at least 2V apart. N-PE runs in its own 1 s thread, so serial commands never delay bonding:
live, N-PE bonded ~3s after a SUB -> SBU switch.

All thresholds are HA numbers (retained MQTT + `soc_settings.json`). Every inverter setting is read back after sending and re-checked every 10 min.

## Grid MCB lockout (32A protection)

When grid current (ZMAi) reaches the MCB rating **while the inverter is charging from grid**, the charger is
switched to solar only, whatever the Battery Mode (solar first included: this inverter grid-charges in CSO even with PV).

| Lockout | Grid charging paused for |
|---|---|
| 1st | 30 min |
| 2nd | 1 h |
| 3rd | 2 h |
| 4th and later | until midnight |

Repeats reset when grid charging is no longer wanted (target SOC reached or mode changed), and after a lockout that ran until midnight.
Grid over the MCB rating from house load alone, with no grid charging, only raises the "Grid Over MCB Rating" alert:
pausing the charger would change nothing.

MCB rating (A) is an HA number, persisted in `soc_settings.json`.

## Program 11 (max utility charging current)

HA select with the values the inverter accepts (manual: 2, 10-140A, 150/160A on the 10.2kW model), in battery side DC amps.
The picked value is the grid charging current: the battery mode applies it only in grid-charging states and runs 2A
otherwise, sending MUCHGC when the wanted value changes. It is re-read every 10 min.
It is independent of the MCB rating: 30A DC is about 1.6kW, roughly 7A on the grid side.
Observed: with the BMS connected (LIb), the inverter charged at ~93A while program 11 was 30A, so the MCB lockout, not program 11,
is what protects the breaker.

## PV2 estimation

Daxtromn AGH firmware does not expose PV2 via serial (QPIGS2/QP2GS0 return NAK). PV2 is derived from the energy balance:

`pv_total = (ac_output − grid) / pv_efficiency − battery_contribution`

`pv2 = pv_total − pv1`

Where `battery_contribution = (discharge − charge) × voltage` (positive discharging, negative charging), and `pv_efficiency` (default 0.93) converts AC-side watts back to DC (grid passes through at 1:1, PV goes DC→AC with ~7% loss).

**Grid charging bypass:** when the inverter charges the battery from grid (device_status bit 7 = 1), the energy balance is unreliable — ZMAi and QPIGS poll at different moments, and a small timing mismatch between the grid and battery terms inflates PV2 by hundreds of watts. In this state the formula falls back to `pv_total = pv1 × (1 + pv2_ratio)` where `pv2_ratio` (default 0.60) is adjustable via MQTT. Both panels see the same sky, so the ratio gives a stable estimate.

**Low-PV2 fallback:** when the balance gives PV2 < 5% of PV1 and PV1 > 50W, the ratio is used instead (measurement noise dominates at small differences).

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
