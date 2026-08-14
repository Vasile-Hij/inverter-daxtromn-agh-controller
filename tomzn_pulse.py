from gpiozero import Button
import time

IMP_PER_KWH = 1600
pulse_pin = Button(17, pull_up=True, bounce_time=0.05)

last_pulse_time = None

def pulse_callback():
    global last_pulse_time
    now = time.time()
    if last_pulse_time is not None:
        interval = now - last_pulse_time
        if interval > 0.1:  # ignore anything faster than 100ms (36kW+ implausible)
            power_w = (3600 * 1000) / (interval * IMP_PER_KWH)
            print(f"Power: {power_w:.1f} W", flush=True)
    last_pulse_time = now

pulse_pin.when_released = pulse_callback

print("Listening for pulses...", flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
