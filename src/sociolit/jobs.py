"""One background write job per application, with bounded public progress."""
import threading
from datetime import datetime, timezone


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = {"state": "idle"}

    def snapshot(self):
        with self.lock:
            return dict(self.value)

    def start(self, name, function):
        with self.lock:
            if self.value["state"] == "running":
                raise RuntimeError("另一个后台任务正在运行，请等待完成。")
            self.value = {"state": "running", "name": name, "phase": "starting", "done": 0,
                          "total": None, "started": datetime.now(timezone.utc).isoformat()}

        def progress(phase, done=None, total=None):
            if done is None:
                phase, done = "embedding", phase
            with self.lock:
                self.value.update(phase=phase, done=done, total=total)

        def work():
            try:
                result = function(progress)
                with self.lock:
                    self.value.update(state="done", result=result)
            except Exception as exc:
                # Diagnostics remain on the local PC. No corpus is sent anywhere.
                with self.lock:
                    self.value.update(state="error", error=str(getattr(exc, "detail", exc))[:1000])

        threading.Thread(target=work, name="sociolit-job", daemon=True).start()
        return self.snapshot()
