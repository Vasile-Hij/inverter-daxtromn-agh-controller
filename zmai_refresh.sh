#!/bin/bash
# Point the ZMAi-90 OpenBeken MQTT host at the pi's current address and
# confirm the meter is publishing again. Needed after the pi changes address
# (e.g. ethernet unplugged -> wifi), otherwise the meter silently stops
# reporting and HA shows it off while it is still on.
# Run with: bash zmai_refresh.sh
set -e

PROJECT_DIRECTORY="$(cd "$(dirname "$0")" && pwd)"
ENVIRONMENT_FILE="$PROJECT_DIRECTORY/.env"
ZMAI_POWER_TOPIC="energy-smart-meter-zmai-90/power/get"
PUBLISH_WAIT_SECONDS=15

read_environment_value() {
    grep "^$1=" "$ENVIRONMENT_FILE" | cut -d= -f2-
}

ZMAI_IP="$(read_environment_value ZMAI_IP)"
if [ -z "$ZMAI_IP" ]; then
    echo "ZMAI_IP missing from $ENVIRONMENT_FILE"
    exit 1
fi

# 1. Pi address as seen by the meter: the source address of the route to it
PI_IP="$(ip -4 route get "$ZMAI_IP" | grep -o 'src [0-9.]*' | cut -d' ' -f2)"
if [ -z "$PI_IP" ]; then
    echo "No route to the ZMAi, check the pi network connection"
    exit 1
fi

# 2. Meter's configured MQTT host, read from the OpenBeken web UI
METER_MQTT_HOST="$(curl -s -m 5 "http://$ZMAI_IP/cfg_mqtt" \
    | grep -o 'name="host"[^>]*value="[^"]*"' | grep -o 'value="[^"]*"' | cut -d'"' -f2)"
if [ -z "$METER_MQTT_HOST" ]; then
    echo "ZMAi web UI not reachable"
    exit 1
fi

# 3. Repoint the meter when it targets an old address (applies without reboot)
if [ "$METER_MQTT_HOST" = "$PI_IP" ]; then
    echo "ZMAi MQTT host already matches the pi"
else
    curl -s -m 5 "http://$ZMAI_IP/cm?cmnd=MQTTHost%20$PI_IP" > /dev/null
    echo "ZMAi MQTT host updated to the pi's current address"
fi

# 4. Keep PI_IP in .env in sync with the address actually in use
if grep -q "^PI_IP=" "$ENVIRONMENT_FILE"; then
    sed -i "s/^PI_IP=.*/PI_IP=$PI_IP/" "$ENVIRONMENT_FILE"
else
    echo "PI_IP=$PI_IP" >> "$ENVIRONMENT_FILE"
fi

# 5. A fresh power reading proves the meter reaches the broker
POWER_READING="$(mosquitto_sub -h 127.0.0.1 \
    -u "$(read_environment_value MQTT_USER)" -P "$(read_environment_value MQTT_PASSWORD)" \
    -t "$ZMAI_POWER_TOPIC" -C 1 -W "$PUBLISH_WAIT_SECONDS" 2> /dev/null || true)"
if [ -z "$POWER_READING" ]; then
    echo "ZMAi not publishing after ${PUBLISH_WAIT_SECONDS}s"
    exit 1
fi
echo "ZMAi publishing, grid power ${POWER_READING} W"
