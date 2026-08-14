**electrical management**
- this is a very important management plan for electricity, so it is very important to be safe and fire hazard free
- implies a Daxtromn AGH-10.2 kw inverter
- grid data from ZMAi-90 smart meter (BK7231N/CBU, OpenBeken + RN8209 driver) over MQTT
- inverter data via RS232 to pi (mppsolar, PI30, /dev/serial/by-id/... never /dev/ttyUSBn,
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
  - no battery (with or without PVs): inverter cannot island, N-PE OFF regardless of wattage
  - ZMAi relay open (off grid): N-PE ON regardless
- no battery: inverter cannot island, so NPE_DEFAULT_MODE = manual_off, logic stays live but inert
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
- inverter reads data via RS232 using mppsolar; PV2 generates but is not exposed by the
  protocol, so derive it: (ac_output - battery - grid) / 0.85 - pv1. battery term is 0
  while BATTERY_INSTALLED is false
- inverter reads data from 485 from battery
- calculation of consumption in real time every 5 seconds from invertor, ZMAi, battery
- ZMAi relay is bistable, driven by 500ms pulses from pulse_on.bat / pulse_off.bat on the device
- solar_monitor_tomzn.py is the previous Tomzn/tinytuya version, kept for reference
