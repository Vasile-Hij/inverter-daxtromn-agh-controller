class Alarm:
    """Logs a fault once on transition, then repeats slowly while it persists."""

    def __init__(self, name, repeat_seconds):
        self._name = name
        self._repeat_seconds = repeat_seconds
        self._last_log_time = None
        self.active = False

    def update(self, is_faulted, detail, now):
        if not is_faulted:
            if self.active:
                print(f"ALARM CLEARED [{self._name}]", flush=True)
            self.active = False
            self._last_log_time = None
            return

        if not self.active:
            print(f"ALARM RAISED [{self._name}] {detail}", flush=True)
        elif (now - self._last_log_time) >= self._repeat_seconds:
            print(f"ALARM ACTIVE [{self._name}] {detail}", flush=True)
        else:
            return
        self.active = True
        self._last_log_time = now
