"""Hard caller deadline plus bounded daemon workers; no unbounded executor queue."""

import threading


class DecisionTimeout(TimeoutError):
    pass


class CapacityExceeded(RuntimeError):
    pass


class BoundedRunner:
    def __init__(self, workers=4):
        self.slots = threading.BoundedSemaphore(workers)

    def run(self, fn, timeout):
        if not self.slots.acquire(blocking=False):
            raise CapacityExceeded()
        done = threading.Event()
        box = []

        def work():
            try:
                box.append((True, fn()))
            except Exception:
                # Never carry exception text/traceback or HTTP response bodies across hooks.
                box.append((False, None))
            finally:
                self.slots.release()
                done.set()

        try:
            threading.Thread(target=work, name="typesafe-decision", daemon=True).start()
        except Exception:
            self.slots.release()
            raise
        if not done.wait(timeout):
            raise DecisionTimeout()
        if not box[0][0]:
            raise RuntimeError("Decision backend failed")
        return box[0][1]
