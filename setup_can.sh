#!/bin/bash
# Setup MCP2515 CAN bus interface on Raspberry Pi
# Run with: sudo bash setup_can.sh
set -e

CONFIG="/boot/firmware/config.txt"

# 1. Enable SPI
if grep -q "^#dtparam=spi=on" "$CONFIG"; then
    sed -i 's/^#dtparam=spi=on$/dtparam=spi=on/' "$CONFIG"
    echo "SPI enabled in $CONFIG"
elif grep -q "^dtparam=spi=on" "$CONFIG"; then
    echo "SPI already enabled"
else
    sed -i '/^\[all\]/a dtparam=spi=on' "$CONFIG"
    echo "SPI added to [all] section"
fi

# 2. Add MCP2515 overlay under [all]
OVERLAY="dtoverlay=mcp2515-can0,oscillator=8000000,interrupt=25,spimaxfrequency=1000000"
if grep -q "mcp2515" "$CONFIG"; then
    echo "MCP2515 overlay already in $CONFIG"
else
    sed -i "/^\[all\]/a $OVERLAY" "$CONFIG"
    echo "MCP2515 overlay added to [all] section"
fi

# 3. Create systemd service to bring up can0 on boot
cat > /etc/systemd/system/can0.service << 'EOF'
[Unit]
Description=CAN bus interface can0
After=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/ip link set can0 up type can bitrate 500000
ExecStop=/sbin/ip link set can0 down

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable can0.service
echo "can0.service created and enabled"

echo ""
echo "Done. Reboot to activate SPI and MCP2515 overlay."
echo "After reboot, can0 will come up automatically."
echo "Verify with: candump can0"
