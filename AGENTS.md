**electrical management**
- this is a very important management plan for electricity, so it is very important to be safe and fire hazard free
- implies a Daxtromn AGH-10.2 kw inverter
- grid data from ZMAi-90 smart meter (BK7231N/CBU, OpenBeken + RN8209 driver) over MQTT
- inverter data via RS232 to pi (direct pyserial, PI30/QPIGS, /dev/serial/by-id/... never /dev/ttyUSBn,
  it renumbers on replug and the inverter goes silent)
- battery data via RS485 from inverter, only when a battery is fitted

**Flow**
- ZMAi-90 -> mosquitto on pi (127.0.0.1:1883, user mqtt-rasp) -> solar_monitor.py
- inverter -> RS232 -> solar_monitor.py
- battery -> RS485 -> inverter -> solar_monitor.py
- solar_monitor.py -> solar/# + homeassistant/# -> mosquitto bridge -> HA broker 10.10.10.31
- HA -> solar/npe_bonding/mode/set -> bridge in -> solar_monitor.py
- solar_monitor.py -> GPIO27 -> N-PE relay
- solar_monitor.py -> energy-smart-meter-zmai-90/1/set -> ZMAi grid relay

**Rules**
- N-PE bonding depends on battery state AND grid wattage:
  - battery installed + ZMAi wattage 50-150W: inverter is islanding, N-PE ON, then turn off ZMAi relay (go off grid)
  - battery under 15% and not charging: turn on ZMAi relay (reconnect to grid)
  - grid draw over 150W: N-PE OFF (real grid consumption, not islanding)
  - no battery detected (with or without PVs): inverter cannot island, N-PE OFF regardless of wattage
  - ZMAi relay open (off grid): N-PE ON regardless
- no battery detected: inverter cannot island, N-PE stays off in auto mode
- opening the ZMAi relay islands the house, so N-PE must be bonded before it opens
- ZMAi measures the line side, its voltage stays live with the relay open, so voltage is not
  a usable off-grid signal; relay state (energy-smart-meter-zmai-90/1/get) and power are

**Code**
- write clean code, no shortcuts or verbosed
- LBYL with if/else, no EAFB try/except

**Infra**
- mosquitto runs on the pi, bridged to HA, so a HA restart cannot cut the grid signal
- Omada gateway ACL permits VLAN3-IoT -> 10.10.10.20:1883
- tailscale up after power surge
- activate this project via sh script

**How it works**
- daxtromn inverter has no bounding for N-PE, so we have do it manually
- ZMAi smart meter detects under 30w consumption it will activate an relay to bound N-PE after daxtromn inverter
- inverter reads data via RS232 using direct pyserial (QPIGS command, PI30 protocol);
  Daxtromn AGH does NOT expose PV2 via serial (QPIGS2 returns NAK, QP2GS0 returns NAK,
  QPIGS fields 17-18 and 21 are zero/stub — confirmed on firmware, Dess Monitor app also
  shows 0V for PV2). PV2 is derived from energy balance:
  pv2 = (ac_output - grid) / 0.93 - battery_net - pv1
  battery_net is (discharge - charge) × voltage; negative when charging.
  battery term is 0 when no battery detected.
  the 0.85 divisor accounts for DC-AC conversion losses and applies only to the AC-side
  terms (ac_output - grid), not to battery which is already on the DC bus
- battery presence is auto-detected every cycle from 5 independent signals:
  1. battery voltage > 20V (direct inverter telemetry)
  2. charging current > 0.5A (battery is charging)
  3. discharge current > 0.5A (battery is discharging)
  4. battery SOC > 0% (inverter reports capacity)
  5. grid off + no PV + inverter outputting > 50W (energy must come from battery)
- inverter reads data from 485 from battery
- calculation of consumption in real time every 5 seconds from invertor, ZMAi, battery
- ZMAi relay is bistable, driven by 500ms pulses from pulse_on.bat / pulse_off.bat on the device
- solar_monitor_tomzn.py is the previous Tomzn/tinytuya version, kept for reference
