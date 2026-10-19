# a ZMAi refresh failure must not block restarting the service
restart:
    -bash zmai_refresh.sh
    sudo systemctl restart solar-monitor

zmai-refresh:
    bash zmai_refresh.sh
