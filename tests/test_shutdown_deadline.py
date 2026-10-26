"""Absolute shutdown deadlines exercised entirely with in-memory serial I/O."""
import threading
import time
import unittest
from unittest.mock import patch

from bioshake_driver.bioshake import BioShake, Data
from bioshake_driver.serial import BaseDevice
from test_heat_shake import Clock


class MemorySerial:
    def __init__(self, clock, *, status_delay=0, byte_delay=0, write_delay=0):
        self.clock = clock
        self.timeout = 30
        self.write_timeout = None
        self.status_delay = status_delay
        self.byte_delay = byte_delay
        self.write_delay = write_delay
        self.commands = []
        self.pending = b''
        self.first_byte = False
        self.read_budgets = []
        self.write_budgets = []

    def wait(self, delay, budget):
        self.clock.sleep(delay if budget is None else min(delay, budget))
        return budget is None or delay <= budget

    def write(self, data):
        self.write_budgets.append(self.write_timeout)
        if not self.wait(self.write_delay, self.write_timeout):
            raise TimeoutError('memory serial write timed out')
        command = data.decode().strip()
        self.commands.append(command)
        self.pending = {'getShakeState': b'3\n', 'getShakeActualSpeed': b'0\n',
                        'getTempState': b'0\n'}.get(command, b'Ok\n')
        self.first_byte = True
        return len(data)

    def read(self, size=1):
        self.read_budgets.append(self.timeout)
        delay = self.byte_delay
        if self.first_byte and self.commands[-1].startswith('get'):
            delay += self.status_delay
        self.first_byte = False
        if not self.wait(delay, self.timeout):
            return b''
        out, self.pending = self.pending[:size], self.pending[size:]
        return out

    def readline(self):
        line = b''
        while True:
            out = self.read()
            line += out
            if not out or out == b'\n':
                return line

    def reset_output_buffer(self):
        pass


class MemoryBioShake(BioShake):
    def __init__(self, connection):
        BaseDevice.__init__(self, data_type=Data, read_format='{data}\r',
                            write_format='{data}\r')
        self.connection = connection

    def __del__(self):
        pass


class ContendedLock:
    """Model a telemetry exchange releasing only after 12 virtual seconds."""
    def __init__(self, clock):
        self.clock = clock
        self.budgets = []

    def acquire(self, *, timeout=-1):
        self.budgets.append(timeout)
        self.clock.sleep(12 if timeout < 0 else min(12, timeout))
        return timeout < 0 or timeout >= 12

    def release(self):
        pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


class ShutdownDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.timer = patch('bioshake_driver.serial.time.perf_counter', lambda: self.clock.now)
        self.timer.start()
        self.addCleanup(self.timer.stop)

    def test_shutdown_budgets_three_delayed_status_reads(self):
        connection = MemorySerial(self.clock, status_delay=4)
        device = MemoryBioShake(connection)
        with self.assertRaises(TimeoutError):
            device._heat_shake_shutdown()
        self.assertEqual(self.clock.now, 10)
        self.assertEqual(connection.commands[:2], ['shakeOff', 'tempOff'])
        self.assertEqual(connection.read_budgets[-1], 2)
        self.assertEqual(connection.timeout, 30)
        self.assertIsNone(connection.write_timeout)

    def test_shutdown_budgets_telemetry_lock_wait_after_both_off_commands(self):
        connection = MemorySerial(self.clock)
        device = MemoryBioShake(connection)
        lock = ContendedLock(self.clock)
        original = device.temp_off

        def stop_heater():
            original()
            device._io_lock = lock

        device.temp_off = stop_heater
        with self.assertRaises(TimeoutError):
            device._heat_shake_shutdown()
        self.assertEqual(self.clock.now, 10)
        self.assertEqual(lock.budgets, [10])
        self.assertEqual(connection.commands, ['shakeOff', 'tempOff'])

    def test_query_deadline_caps_trickling_read_and_blocked_write(self):
        for settings in ({'byte_delay': 0.75}, {'write_delay': 3}):
            with self.subTest(settings=settings):
                self.clock.now = 0
                connection = MemorySerial(self.clock, **settings)
                device = MemoryBioShake(connection)
                with self.assertRaises(TimeoutError):
                    device._query('getShakeState', deadline=1)
                self.assertEqual(self.clock.now, 1)
                self.assertEqual(connection.timeout, 30)
                self.assertIsNone(connection.write_timeout)

    def test_query_deadline_times_out_on_real_exchange_rlock(self):
        device = MemoryBioShake(MemorySerial(self.clock))
        held, release = threading.Event(), threading.Event()

        def telemetry():
            with device._io_lock:
                held.set()
                release.wait(2)

        thread = threading.Thread(target=telemetry)
        thread.start()
        self.assertTrue(held.wait(1))
        # Restore the real monotonic clock for the real timed RLock acquisition.
        self.timer.stop()
        started = time.perf_counter()
        try:
            with self.assertRaises(TimeoutError):
                device._query('getShakeState', deadline=started + 0.03)
            self.assertLess(time.perf_counter() - started, 0.5)
            self.assertEqual(device.connection.commands, [])
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
