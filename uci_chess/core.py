from threading import Thread
from queue import Queue
from subprocess import Popen, PIPE, STDOUT
from timeit import default_timer as timer
from time import sleep
from pathlib import Path
import logging
import re


RE_OPTIONS_LIST = re.compile(r"^option\s+name\s([\w\s]+)\stype\s([\w\s]+?)(\sdefault\s?.*)?$")


class EngineCore:
    output_buffer = []

    def __init__(
        self,
        engine_binary_path: str | Path,
        timeout: int = 60
    ) -> None:
        self.timeout = timeout
        self.engine_binary_path = Path(engine_binary_path)
        if not self.engine_binary_path.exists():
            raise FileNotFoundError(
                f"Engine binary not found at {self.engine_binary_path}"
            )

        self.engine = Popen(
            self.engine_binary_path,
            universal_newlines=True,
            stdin=PIPE,
            stdout=PIPE,
            stderr=STDOUT,
        )
        self._output_queue = Queue()
        self.buffer_daemon = Thread(target=_read_output_to_queue, args=(self.engine.stdout, self._output_queue))
        self.buffer_daemon.daemon = True
        self.buffer_daemon.start()

        self.put("uci")
        resp = self.get()
        available_options = []
        while resp != "uciok":
            matched = RE_OPTIONS_LIST.match(resp)
            if matched:
                available_options.append(
                    {
                        "name": matched.group(1).strip() if matched.group(1) else None,
                        "type": matched.group(2).strip() if matched.group(2) else None,
                        "default": (
                            matched.group(3).strip() if matched.group(3) else None
                        ),
                    }
                )
            resp = self.get()

        self.available_options = {
            ao["name"]: {"type": ao["type"], "default": ao["default"]}
            for ao in available_options
        }

    def _move_from_queue_to_buffer(self) -> None:
        while not self._output_queue.empty():
            self.output_buffer.append(self._output_queue.get())

    def _wait_output_buffer(self, index_to_view: int | None = None) -> None:
        start_time = timer()
        if index_to_view is not None:
            while len(self.output_buffer) <= index_to_view and timer() - start_time < self.timeout:
                sleep(0.1)
                self._move_from_queue_to_buffer()
        else:
            while len(self.output_buffer) == 0 and timer() - start_time < self.timeout:
                sleep(0.1)
                self._move_from_queue_to_buffer()

    def put(self, message) -> None:
        logging.debug(message)
        self.engine.stdin.write(f"{message}\n")
        self.engine.stdin.flush()

    def get(self) -> str:
        self._wait_output_buffer()
        result = self.output_buffer.pop(0)
        logging.debug(f"get response: {result}")
        return result

    def view(self, index_to_view: int) -> None:
        self._wait_output_buffer(index_to_view)
        result = self.output_buffer[index_to_view]
        logging.debug(f"view into buffer ({index_to_view}): {result}")
        return result

    def is_ready(self) -> bool:
        self.put("isready")
        resp = self.get()
        while resp != "readyok":
            resp = self.get()
        return True

    def stop(self):
        self.put("stop")

    def __del__(self):
        if self.engine.poll() is None:
            self.put("quit")
            self.engine.wait()



def _read_output_to_queue(out, output_queue):
    for line in iter(out.readline, ''):
        output_queue.put(line.strip())
