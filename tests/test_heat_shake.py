"""Offline native-command tests: no serial port, broker or hardware access."""
import unittest
from unittest.mock import patch

from bioshake_driver.bioshake import BioShake, Data
from bioshake_driver.serial import BaseDevice
from puda.command import build_command_catalog


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds
        if self.now > 1000:
            raise AssertionError('unbounded virtual device wait')


class FakeBioShake(BioShake):
    def __init__(self, clock):
        BaseDevice.__init__(self, simulation=True)
        self.clock = clock
        self.calls = []
        self.replies = {}
        self.temperature = 40.0
        self.speed = 600
        self.heating = 0
        self.running = False
        self.shake_started = None

    def __del__(self):
        pass

    def _query(self, data, **kwargs):
        self.calls.append((self.clock.now, data))
        if data in self.replies:
            reply = self.replies[data]
            if isinstance(reply, BaseException):
                raise reply
            value = reply() if callable(reply) else reply
        elif data.startswith('setTempTarget'):
            self.temperature = int(data[len('setTempTarget'):]) / 10
            value = 'Ok'
        elif data.startswith('setShakeTargetSpeed'):
            self.speed = int(data[len('setShakeTargetSpeed'):])
            value = 'Ok'
        elif data == 'tempOn':
            self.heating = 1
            value = 'Ok'
        elif data == 'tempOff':
            self.heating = 0
            value = 'Ok'
        elif data == 'shakeOn':
            self.running = True
            self.shake_started = self.clock.now
            value = 'Ok'
        elif data == 'shakeOff':
            self.running = False
            value = 'Ok'
        else:
            value = {
                'getTempMin': 4, 'getTempMax': 99,
                'getTempLimiterMin': 4, 'getTempLimiterMax': 95,
                'getShakeMinRpm': 200, 'getShakeMaxRpm': 3000,
                'getShakeSpeedLimitMin': 200, 'getShakeSpeedLimitMax': 2500,
                'getTempTarget': self.temperature,
                'getShakeTargetSpeed': self.speed,
                'getTempActual': 25 if self.clock.now < 2 else 40,
                'getTempState': self.heating,
                'getShakeState': 0 if self.running else 3,
                'getElmState': 1,
                'getShakeActualSpeed': (
                    self.speed if self.running and self.clock.now >= self.shake_started + 2 else 0
                ),
            }[data]
        if value is None:
            return None
        data_type = kwargs.get('data_type', Data)
        return data_type(data_type.__annotations__['data'](value))


class HeatShakeTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.device = FakeBioShake(self.clock)
        self.sleep = patch('bioshake_driver.bioshake.time.sleep', self.clock.sleep)
        self.timer = patch('bioshake_driver.bioshake.time.perf_counter', lambda: self.clock.now)
        self.sleep.start()
        self.timer.start()
        self.addCleanup(self.sleep.stop)
        self.addCleanup(self.timer.stop)

    def run_command(self, **kwargs):
        settings = dict(temperature=40, speed=600, duration=300, plate_seated=True)
        settings.update(kwargs)
        return self.device.heat_shake(**settings)

    def test_native_combined_hold_starts_only_after_temperature_stability_and_measured_speed(self):
        self.assertTrue(callable(getattr(self.device, 'heat_shake', None)),
                        'native heat_shake command is missing')
        _, catalog = build_command_catalog(self.device)
        entry = next(item for item in catalog if item['name'] == 'heat_shake')
        self.assertIn('hot surface', entry['safety']['hazards'])
        result = self.run_command()
        self.assertEqual(result['target_temperature_c'], 40)
        self.assertEqual(result['target_speed_rpm'], 600)
        self.assertGreaterEqual(result['hold_elapsed_seconds'], 300)
        self.assertGreaterEqual(result['hold_started_after_seconds'], 6)
        self.assertEqual(result['temperature_min_c'], 40)
        self.assertEqual(result['temperature_max_c'], 40)
        self.assertEqual(result['speed_min_rpm'], 600)
        self.assertEqual(result['speed_max_rpm'], 600)
        commands = [cmd for _, cmd in self.device.calls]
        self.assertLess(commands.index('tempOn'), commands.index('shakeOn'))
        self.assertLess(commands.index('shakeOn'), commands.index('tempOff'))
        self.assertFalse(self.device.running)
        self.assertEqual(self.device.heating, 0)
        self.assertTrue(result['shutdown_verified'])
        self.assertIn('shakeOff', commands)
        self.assertIn('tempOff', commands)


    def test_rejects_invalid_settings_before_enabling_outputs(self):
        for settings in (
            {'temperature': float('nan')}, {'temperature': float('inf')},
            {'temperature': True}, {'temperature': '40'}, {'temperature': 40.01},
            {'speed': True}, {'speed': 600.5}, {'speed': 0},
            {'duration': -1}, {'duration': 0}, {'duration': float('nan')},
            {'duration': True}, {'duration': '300'},
            {'heatup_timeout': 0}, {'heatup_timeout': float('inf')},
            {'speed_timeout': -1}, {'speed_timeout': True},
            {'plate_seated': False}, {'plate_seated': 1},
        ):
            with self.subTest(settings=settings):
                self.device.calls.clear()
                with self.assertRaises(ValueError):
                    self.run_command(**settings)
                commands = [cmd for _, cmd in self.device.calls]
                self.assertNotIn('tempOn', commands)
                self.assertNotIn('shakeOn', commands)
                self.assertIn('shakeOff', commands)
                self.assertIn('tempOff', commands)


    def test_device_and_configured_limits_are_required_and_enforced(self):
        for query, bad, error in (
            ('getTempMin', 41, ValueError), ('getTempMax', 39, ValueError),
            ('getTempLimiterMin', 41, ValueError), ('getTempLimiterMax', 39, ValueError),
            ('getShakeMinRpm', 601, ValueError), ('getShakeMaxRpm', 599, ValueError),
            ('getShakeSpeedLimitMin', 601, ValueError),
            ('getShakeSpeedLimitMax', 599, ValueError),
            *((query, value, RuntimeError) for query in (
                'getTempMin', 'getTempMax', 'getTempLimiterMin', 'getTempLimiterMax',
                'getShakeMinRpm', 'getShakeMaxRpm',
                'getShakeSpeedLimitMin', 'getShakeSpeedLimitMax',
            ) for value in (None, float('nan'), float('inf'))),
        ):
            with self.subTest(query=query, bad=bad):
                self.clock.now = 0
                self.device = FakeBioShake(self.clock)
                self.device.replies[query] = bad
                with self.assertRaises(error):
                    self.run_command(duration=1)
                commands = [cmd for _, cmd in self.device.calls]
                self.assertNotIn('tempOn', commands)
                self.assertNotIn('shakeOn', commands)
                self.assertIn('shakeOff', commands)
                self.assertIn('tempOff', commands)


    def test_requires_locked_clamp_and_measured_stopped_home_before_setup(self):
        for query, value in (
            ('getElmState', 0), ('getElmState', 3), ('getElmState', 9), ('getElmState', None),
            ('getShakeState', 0), ('getShakeState', 9), ('getShakeState', None),
            ('getShakeActualSpeed', 1), ('getShakeActualSpeed', None),
            ('getShakeActualSpeed', float('nan')),
        ):
            with self.subTest(query=query, value=value):
                self.clock.now = 0
                self.device = FakeBioShake(self.clock)
                # Bad only before cleanup, so shutdown can still be verified.
                self.device.replies[query] = lambda: (
                    value if not any(cmd == 'shakeOff' for _, cmd in self.device.calls)
                    else {'getElmState': 1, 'getShakeState': 3, 'getShakeActualSpeed': 0}[query]
                )
                with self.assertRaises(RuntimeError):
                    self.run_command(duration=1)
                commands = [cmd for _, cmd in self.device.calls]
                self.assertFalse(any(cmd.startswith('set') for cmd in commands))
                self.assertNotIn('tempOn', commands)
                self.assertNotIn('shakeOn', commands)
                self.assertIn('shakeOff', commands)
                self.assertIn('tempOff', commands)


    def test_target_readbacks_must_match_before_enabling_outputs(self):
        for query, bad in (
            ('getTempTarget', None), ('getTempTarget', float('nan')),
            ('getTempTarget', 41), ('getShakeTargetSpeed', None),
            ('getShakeTargetSpeed', float('inf')), ('getShakeTargetSpeed', 601),
        ):
            with self.subTest(query=query, bad=bad):
                self.clock.now = 0
                self.device = FakeBioShake(self.clock)
                self.device.replies[query] = bad
                with self.assertRaises(RuntimeError):
                    self.run_command(duration=1)
                commands = [cmd for _, cmd in self.device.calls]
                self.assertNotIn('tempOn', commands)
                self.assertNotIn('shakeOn', commands)
                self.assertIn('shakeOff', commands)
                self.assertIn('tempOff', commands)


    def test_missing_or_faulted_live_readings_abort_each_active_phase(self):
        for phase in ('heatup', 'ramp', 'hold'):
            for query, bad in (
                ('getTempActual', None), ('getTempActual', float('nan')),
                ('getTempActual', float('inf')), ('getShakeActualSpeed', None),
                ('getShakeActualSpeed', float('nan')), ('getShakeActualSpeed', -1),
                ('getTempState', None), ('getTempState', 0), ('getTempState', 2),
                ('getTempState', 'e201'), ('getElmState', None), ('getElmState', 3),
                ('getShakeState', None), ('getShakeState', 9),
            ):
                with self.subTest(phase=phase, query=query, bad=bad):
                    self.clock.now = 0
                    self.device = FakeBioShake(self.clock)
                    real_query = self.device._query

                    def fault(command, **kwargs):
                        active = self.device.heating and (
                            (phase == 'heatup' and not self.device.running)
                            or (phase == 'ramp' and self.device.running)
                            or (phase == 'hold' and self.clock.now >= 7)
                        )
                        if command == query and active:
                            self.device.calls.append((self.clock.now, command))
                            return None if bad is None else kwargs.get('data_type', Data)(bad)
                        return real_query(command, **kwargs)

                    self.device._query = fault
                    with self.assertRaises(RuntimeError):
                        self.run_command(duration=3)
                    commands = [cmd for _, cmd in self.device.calls]
                    self.assertIn('shakeOff', commands)
                    self.assertIn('tempOff', commands)
                    if phase == 'heatup':
                        self.assertNotIn('shakeOn', commands)


    def test_readiness_waits_have_bounded_timeouts(self):
        for query, value, settings, limit in (
            ('getTempActual', 25, {'heatup_timeout': 3}, 3.5),
            ('getShakeActualSpeed', 0, {'speed_timeout': 3}, 7.5),
        ):
            with self.subTest(query=query):
                self.clock.now = 0
                self.device = FakeBioShake(self.clock)
                self.device.replies[query] = value
                with self.assertRaises(TimeoutError):
                    self.run_command(duration=1, **settings)
                self.assertLessEqual(self.clock.now, limit)
                commands = [cmd for _, cmd in self.device.calls]
                self.assertIn('shakeOff', commands)
                self.assertIn('tempOff', commands)


    def test_temperature_and_speed_drift_abort_without_counting_an_invalid_hold(self):
        for phase, query, value in (
            ('ramp', 'getTempActual', 41.1), ('ramp', 'getTempActual', 38.9),
            ('ramp', 'getShakeActualSpeed', 613),
            ('hold', 'getTempActual', 41.1), ('hold', 'getTempActual', 38.9),
            ('hold', 'getShakeActualSpeed', 587), ('hold', 'getShakeActualSpeed', 613),
        ):
            with self.subTest(phase=phase, query=query, value=value):
                self.clock.now = 0
                self.device = FakeBioShake(self.clock)
                real_query = self.device._query

                def drift(command, **kwargs):
                    if (command == query and self.device.running
                            and (phase == 'ramp' or self.clock.now >= 7)):
                        self.device.calls.append((self.clock.now, command))
                        return kwargs['data_type'](value)
                    return real_query(command, **kwargs)

                self.device._query = drift
                with self.assertRaisesRegex(RuntimeError, 'drift|overspeed'):
                    self.run_command(duration=3)
                self.assertLessEqual(self.clock.now, 7.5)
                self.assertFalse(self.device.running)
                self.assertEqual(self.device.heating, 0)


    def test_shutdown_is_bounded_and_never_reports_unverified_success(self):
        for query, bad in (
            ('getShakeState', 9), ('getShakeState', None),
            ('getShakeActualSpeed', 10), ('getShakeActualSpeed', None),
            ('getTempState', 1), ('getTempState', None), ('getTempState', 'e201'),
        ):
            with self.subTest(query=query, bad=bad):
                self.clock.now = 0
                self.device = FakeBioShake(self.clock)
                real_query = self.device._query

                def shutdown_fault(command, **kwargs):
                    if command == query and any(cmd == 'tempOff' for _, cmd in self.device.calls):
                        self.device.calls.append((self.clock.now, command))
                        return None if bad is None else kwargs.get('data_type', Data)(bad)
                    return real_query(command, **kwargs)

                self.device._query = shutdown_fault
                with self.assertRaisesRegex(TimeoutError, 'shutdown'):
                    self.run_command(duration=1)
                self.assertLessEqual(self.clock.now, 17.5)
                commands = [cmd for _, cmd in self.device.calls]
                self.assertIn('shakeOff', commands)
                self.assertIn('tempOff', commands)
                self.assertEqual(commands.index('tempOff'), commands.index('shakeOff') + 1)


    def test_shutdown_rejects_valid_readings_arriving_after_deadline(self):
        real_query = self.device._query

        def delayed_status(command, **kwargs):
            if command in ('getShakeState', 'getShakeActualSpeed', 'getTempState'):
                self.clock.sleep(4)
            return real_query(command, **kwargs)

        self.device._query = delayed_status
        with self.assertRaisesRegex(TimeoutError, 'shutdown'):
            self.device._heat_shake_shutdown()
        self.assertEqual(self.clock.now, 12)
        self.assertEqual([cmd for _, cmd in self.device.calls][:2], ['shakeOff', 'tempOff'])

    def test_cleanup_preserves_primary_failure_and_both_stop_errors(self):
        self.device.replies['shakeOff'] = RuntimeError('shake stop failed')
        self.device.replies['tempOff'] = RuntimeError('heater stop failed')
        with self.assertRaises(BaseExceptionGroup) as caught:
            self.run_command(plate_seated=False)
        leaves = []

        def collect(error):
            if isinstance(error, BaseExceptionGroup):
                for child in error.exceptions:
                    collect(child)
            else:
                leaves.append(str(error))

        collect(caught.exception)
        self.assertTrue(any('plate_seated' in error for error in leaves))
        self.assertIn('shake stop failed', leaves)
        self.assertIn('heater stop failed', leaves)
        commands = [cmd for _, cmd in self.device.calls]
        self.assertIn('shakeOff', commands)
        self.assertIn('tempOff', commands)
        self.assertEqual(commands.index('tempOff'), commands.index('shakeOff') + 1)

    def test_ramp_waits_through_a_still_homed_reading_then_holds(self):
        real_query = self.device._query

        def delayed_leave_home(command, **kwargs):
            if (command == 'getShakeState' and self.device.running
                    and self.clock.now < self.device.shake_started + 1):
                self.device.calls.append((self.clock.now, command))
                return kwargs.get('data_type', Data)('3')
            return real_query(command, **kwargs)

        self.device._query = delayed_leave_home
        result = self.run_command(duration=1)
        self.assertGreaterEqual(result['hold_elapsed_seconds'], 1)
        self.assertGreaterEqual(result['hold_started_after_seconds'], 6)
        self.assertTrue(result['shutdown_verified'])
        self.assertFalse(self.device.running)
        self.assertEqual(self.device.heating, 0)

    def test_ramp_that_never_leaves_home_times_out_and_stops(self):
        real_query = self.device._query

        def stay_home(command, **kwargs):
            if self.device.running and command == 'getShakeState':
                self.device.calls.append((self.clock.now, command))
                return kwargs.get('data_type', Data)('3')
            if self.device.running and command == 'getShakeActualSpeed':
                self.device.calls.append((self.clock.now, command))
                return kwargs['data_type'](0)
            return real_query(command, **kwargs)

        self.device._query = stay_home
        with self.assertRaises(TimeoutError):
            self.run_command(duration=1, speed_timeout=3)
        self.assertLessEqual(self.clock.now, 7.5)
        commands = [cmd for _, cmd in self.device.calls]
        self.assertIn('shakeOn', commands)
        self.assertIn('shakeOff', commands)
        self.assertIn('tempOff', commands)
        self.assertFalse(self.device.running)
        self.assertEqual(self.device.heating, 0)

    def test_ramp_rejects_motion_while_state_is_still_home(self):
        real_query = self.device._query

        def moving_while_homed(command, **kwargs):
            if self.device.running and command == 'getShakeState':
                self.device.calls.append((self.clock.now, command))
                return kwargs.get('data_type', Data)('3')
            if self.device.running and command == 'getShakeActualSpeed':
                self.device.calls.append((self.clock.now, command))
                return kwargs['data_type'](10)
            return real_query(command, **kwargs)

        self.device._query = moving_while_homed
        with self.assertRaisesRegex(RuntimeError, 'homed'):
            self.run_command(duration=1)
        self.assertLess(self.clock.now, 7)
        self.assertFalse(self.device.running)
        self.assertEqual(self.device.heating, 0)


if __name__ == '__main__':
    unittest.main()
