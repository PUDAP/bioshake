import threading
import time
import unittest

from bioshake_driver.bioshake import Data
from bioshake_driver.serial import SerialDevice


class FakeSerialDevice(SerialDevice):
    def __init__(self):
        self._io_lock = threading.RLock()
        self.data_type = Data
        self.write_format = "{data}"
        self.read_format = "{data}"
        self.active_writes = 0
        self.max_active_writes = 0
        self.counter_lock = threading.Lock()

    def __del__(self):
        pass

    def process_input(self, data=None, format_in=None, **kwargs):
        return str(data)

    def write(self, data):
        with self.counter_lock:
            self.active_writes += 1
            self.max_active_writes = max(self.max_active_writes, self.active_writes)
        time.sleep(0.05)
        with self.counter_lock:
            self.active_writes -= 1
        return True

    def read_all(self):
        return []

    def check_device_buffer(self):
        return False


class SerialQueryLockTests(unittest.TestCase):
    def test_concurrent_queries_are_serialized(self):
        device = FakeSerialDevice()
        barrier = threading.Barrier(3)

        def query():
            barrier.wait()
            device.query("getShakeMaxRpm")

        threads = [threading.Thread(target=query) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(device.max_active_writes, 1)


if __name__ == "__main__":
    unittest.main()
