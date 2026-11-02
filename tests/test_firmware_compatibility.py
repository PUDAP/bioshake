"""D30-T elm BS firmware contract; all I/O stays in memory.

Source: QINSTRUMENTS Integration Manual 010.8, pp. 2, 6, 8, 10-14,
https://www.qinstruments.com/fileadmin/Article/MANUALS/Integration-manual-en.pdf
SHA256: b4b7c76fc078d1a67cb766cb79f877546951caa3cc53ece8f8145884d23f6fb8
BS does not implement the four TC-only configured-limit queries (p. 8).
Commands end in CR; responses end in CRLF; unknown commands return
u->'unknown command' (p. 6). Numeric fixture values are simulated, not readings.
"""
from contextlib import nullcontext
import unittest
from unittest.mock import patch

from test_heat_shake import Clock
from test_shutdown_deadline import MemoryBioShake, MemorySerial


D30_MODEL = 'Q.MTP-BIOSHAKE D30-T elm'
TC_ONLY_LIMITS = {
    'getTempLimiterMin', 'getTempLimiterMax',
    'getShakeSpeedLimitMin', 'getShakeSpeedLimitMax',
}


class D30Serial(MemorySerial):
    """Explicit BS command whitelist, not a permissive query-name mock."""
    def __init__(self, clock):
        super().__init__(clock)
        self.temperature = 40.0
        self.speed = 600
        self.heating = False
        self.running = False
        self.shake_started = None
        self.replies = {}
        self.exchanges = []
        self.unknown_commands = []
        self.input_clears = 0

    def write(self, data):
        if not data.endswith(b'\r') or b'\n' in data:
            raise AssertionError(f'expected a CR-terminated command: {data!r}')
        command = data[:-1].decode('ascii')
        self.commands.append(command)
        if command in self.replies:
            reply = self.replies[command]
            self.pending = b'' if reply is None else reply.encode('ascii') + b'\r\n'
            self.exchanges.append((data, self.pending))
            return len(data)
        if command.startswith('setTempTarget'):
            self.temperature = int(command[len('setTempTarget'):]) / 10
            value = 'ok'
        elif command.startswith('setShakeTargetSpeed'):
            self.speed = int(command[len('setShakeTargetSpeed'):])
            value = 'ok'
        elif command == 'tempOn':
            self.heating = True
            value = 'ok'
        elif command == 'tempOff':
            self.heating = False
            value = 'ok'
        elif command == 'shakeOn':
            self.running = True
            self.shake_started = self.clock.now
            value = 'ok'
        elif command == 'shakeOff':
            self.running = False
            self.speed = 0  # Integration manual p. 6: every stop resets target RPM.
            value = 'ok'
        else:
            value = {
                'getTempMin': '0.000000', 'getTempMax': '99.000000',
                'getShakeMinRpm': '200', 'getShakeMaxRpm': '2000',
                'getTempTarget': str(self.temperature),
                'getShakeTargetSpeed': str(self.speed),
                'getTempActual': '25.000000' if self.clock.now < 2 else '40.000000',
                'getTempState': '1' if self.heating else '0',
                'getShakeState': '0' if self.running else '3',
                'getElmState': '1',
                'getShakeActualSpeed': str(
                    self.speed if self.running and self.clock.now >= self.shake_started + 2 else 0
                ),
            }.get(command)
            if value is None:
                self.unknown_commands.append(command)
                value = "u->'unknown command'"
        self.pending = value.encode('ascii') + b'\r\n'
        self.exchanges.append((data, self.pending))
        return len(data)

    def reset_input_buffer(self):
        self.input_clears += 1
        self.pending = b''


class FirmwareCompatibilityTests(unittest.TestCase):
    def setUp(self):
        # Guard against accidental real transport construction or connection.
        for target in ('bioshake_driver.serial.serial.Serial',
                       'bioshake_driver.bioshake.BioShake.connect'):
            guard = patch(target, side_effect=AssertionError('hardware access forbidden'))
            guard.start()
            self.addCleanup(guard.stop)
        self.clock = Clock()
        for target, replacement in (
            ('bioshake_driver.bioshake.time.sleep', self.clock.sleep),
            ('bioshake_driver.bioshake.time.perf_counter', lambda: self.clock.now),
        ):
            timer = patch(target, replacement)
            timer.start()
            self.addCleanup(timer.stop)
        self.connection = D30Serial(self.clock)
        self.device = MemoryBioShake(self.connection)
        self.device.model = D30_MODEL

    def run_command(self, **kwargs):
        settings = dict(temperature=40, speed=600, duration=1, plate_seated=True)
        settings.update(kwargs)
        return self.device.heat_shake(**settings)

    def test_d30_heat_shake_uses_only_documented_bs_commands(self):
        # Exercise the real heat_shake -> helpers -> _query -> serial parser path.
        # Old code receives u->'unknown command' for getTempLimiterMin and aborts.
        result = self.run_command()
        self.assertTrue(result['shutdown_verified'])
        self.assertGreaterEqual(result['hold_elapsed_seconds'], 1)
        self.assertEqual(result['temperature_min_c'], 40)
        self.assertEqual(result['speed_min_rpm'], 600)
        self.assertEqual(self.connection.unknown_commands, [])
        self.assertTrue(TC_ONLY_LIMITS.isdisjoint(self.connection.commands))
        self.assertEqual(self.connection.commands[:4], [
            'getTempMin', 'getTempMax', 'getShakeMinRpm', 'getShakeMaxRpm',
        ])
        self.assertIn('tempOn', self.connection.commands)
        self.assertIn('shakeOn', self.connection.commands)
        self.assertEqual(self.connection.commands[-5:], [
            'shakeOff', 'tempOff', 'getShakeState', 'getShakeActualSpeed', 'getTempState',
        ])
        self.assertFalse(self.connection.heating)
        self.assertFalse(self.connection.running)
        self.assertEqual(self.connection.timeout, 30)
        self.assertIsNone(self.connection.write_timeout)

    def reset_device(self):
        self.clock.now = 0
        self.connection = D30Serial(self.clock)
        self.device = MemoryBioShake(self.connection)
        self.device.model = D30_MODEL

    def assert_outputs_never_enabled_and_stopped(self):
        self.assertNotIn('tempOn', self.connection.commands)
        self.assertNotIn('shakeOn', self.connection.commands)
        self.assertIn('shakeOff', self.connection.commands)
        self.assertIn('tempOff', self.connection.commands)
        self.assertFalse(self.connection.heating)
        self.assertFalse(self.connection.running)

    def test_d30_live_limits_still_reject_out_of_range_targets(self):
        for query, value in (
            ('getTempMin', '41'), ('getTempMax', '39'),
            ('getShakeMinRpm', '601'), ('getShakeMaxRpm', '599'),
        ):
            with self.subTest(query=query):
                self.reset_device()
                self.connection.replies[query] = value
                with self.assertRaisesRegex(ValueError, 'outside device .* limits'):
                    self.run_command()
                self.assert_outputs_never_enabled_and_stopped()
                self.assertFalse(any(cmd.startswith('set') for cmd in self.connection.commands))

    def test_d30_live_limits_fail_closed_on_missing_nonfinite_and_invalid_replies(self):
        for query in ('getTempMin', 'getTempMax', 'getShakeMinRpm', 'getShakeMaxRpm'):
            for value in (None, 'nan', 'inf', 'e', "u->'unknown command'"):
                with self.subTest(query=query, value=value):
                    self.reset_device()
                    self.connection.replies[query] = value
                    logs = (self.assertLogs(self.device._logger, level='WARNING')
                            if value in ('e', "u->'unknown command'") else nullcontext())
                    with logs:
                        with self.assertRaisesRegex(RuntimeError, 'invalid device .* limits'):
                            self.run_command()
                    self.assert_outputs_never_enabled_and_stopped()

    def test_d30_inverted_live_limits_are_not_ignored(self):
        for lower, upper in (('getTempMin', 'getTempMax'),
                             ('getShakeMinRpm', 'getShakeMaxRpm')):
            with self.subTest(lower=lower):
                self.reset_device()
                self.connection.replies.update({lower: '700', upper: '100'})
                with self.assertRaisesRegex(RuntimeError, 'Inverted device .* limits'):
                    self.run_command()
                self.assert_outputs_never_enabled_and_stopped()

    def test_non_d30_models_still_require_each_configured_limit(self):
        # Exact identity gate: TC and unknown/differently spelled models do NOT
        # inherit a capability inferred from an invalid-command response.
        for model in ('BioShake Q1', '', 'Q.MTP-BIOSHAKE D30-T', D30_MODEL.upper()):
            for query in sorted(TC_ONLY_LIMITS):
                with self.subTest(model=model, query=query):
                    self.reset_device()
                    self.device.model = model
                    self.connection.replies.update({
                        'getTempLimiterMin': '4', 'getTempLimiterMax': '95',
                        'getShakeSpeedLimitMin': '200', 'getShakeSpeedLimitMax': '1800',
                    })
                    self.connection.replies[query] = "u->'unknown command'"
                    with self.assertLogs(self.device._logger, level='WARNING'):
                        with self.assertRaisesRegex(RuntimeError, 'invalid configured .* limits'):
                            self.run_command()
                    self.assertIn(query, self.connection.commands)
                    self.assert_outputs_never_enabled_and_stopped()

    def test_d30_physical_preconditions_still_block_target_setup(self):
        for query, value in (('getElmState', '3'), ('getShakeState', '0'),
                             ('getShakeActualSpeed', '1')):
            with self.subTest(query=query):
                self.reset_device()
                self.connection.replies[query] = value
                # Release the injected fault after stop so cleanup can be verified.
                original_write = self.connection.write

                def release_fault(data):
                    if data == b'shakeOff\r':
                        self.connection.replies.clear()
                    return original_write(data)

                self.connection.write = release_fault
                with self.assertRaisesRegex(RuntimeError, 'clamp|stopped at home'):
                    self.run_command()
                self.assertFalse(any(cmd.startswith('set') for cmd in self.connection.commands))
                self.assert_outputs_never_enabled_and_stopped()

    def test_d30_still_requires_explicit_plate_confirmation(self):
        with self.assertRaisesRegex(ValueError, 'plate_seated'):
            self.run_command(plate_seated=False)
        self.assert_outputs_never_enabled_and_stopped()


if __name__ == '__main__':
    unittest.main()
