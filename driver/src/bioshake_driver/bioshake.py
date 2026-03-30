"""
BioShake driver with automatic reconnection.

Attributes:
    READ_FORMAT (str): format for reading data
    WRITE_FORMAT (str): format for writing data
    Data (NamedTuple): data type for data
    BoolData (NamedTuple): data type for boolean data
    FloatData (NamedTuple): data type for float data
    IntData (NamedTuple): data type for integer data
    
## Classes:
    `BioShake`: provides an interface for available actions to control devices from QInstruments
    
<i>Documentation last updated: 2025-02-22</i>
"""
# Standard library imports
from __future__ import annotations
import inspect
import time
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any, NamedTuple
from .serial import SerialDevice
from .enums import ELMStateCode, ELMStateString, ShakeStateCode, ShakeStateString

READ_FORMAT = "{data}\r"
WRITE_FORMAT = "{data}\r"
Data = NamedTuple("Data", [("data", str)])
BoolData = NamedTuple("BoolData", [("data", bool)])
FloatData = NamedTuple("FloatData", [("data", float)])
IntData = NamedTuple("IntData", [("data", int)])


logger = logging.getLogger(__name__)

class BioShake(SerialDevice):
    """
    BioShake provides an interface for available actions to control devices from QInstruments, including orbital shakers,
    heat plates, and cold plates.
    
    ### Constructor:
        `port` (str|None, optional): serial port for the device. Defaults to None.
        `baudrate` (int, optional): baudrate for the device. Defaults to 9600.
        `timeout` (int, optional): timeout for the device. Defaults to 1.
        `init_timeout` (int, optional): timeout for initialization. Defaults to 5.
        `data_type` (NamedTuple, optional): data type for data. Defaults to Data.
        `read_format` (str, optional): format for reading data. Defaults to READ_FORMAT.
        `write_format` (str, optional): format for writing data. Defaults to WRITE_FORMAT.
        `simulation` (bool, optional): whether to simulate the device. Defaults to False.
        `verbose` (bool, optional): verbosity of class. Defaults to False.
    
    ### Attributes and properties:
        `port` (str): device serial port
        `baudrate` (int): device baudrate
        `timeout` (int): device timeout
        `connection_details` (dict): connection details for the device
        `serial` (serial.Serial): serial object for the device
        `init_timeout` (int): timeout for initialization
        `message_end` (str): message end character
        `model` (str): device model
        `flags` (SimpleNamespace[str, bool]): flags for the device
        `is_connected` (bool): whether the device is connected
        `verbose` (bool): verbosity of class
    
    ### Methods:
    #### General
        `_clear`: clear the input and output buffers
        `connect`: connect to the device
        `disconnect`: disconnect from the device
        `home`: move shaker to the home position and locks in place
        `_read`: read data from the device
        `_write`: write data to the device
    
    #### ECO
        `_leave_eco_mode`: leaves the economical mode and switches into the normal operating state
        `_set_eco_mode`: witches the shaker into economical mode and reduces electricity consumption
    
    #### Shaking
        `_get_shake_acceleration`: returns the acceleration/deceleration value
        `_get_shake_acceleration_max`: get the maximum acceleration/deceleration time in seconds
        `_get_shake_acceleration_min`: get the minimum acceleration/deceleration time in seconds
        `_get_shake_actual_speed`: returns the current mixing speed
        `_get_shake_default_direction`: returns the mixing direction when the device starts up
        `_get_shake_direction`: returns the current mixing direction
        `_get_shake_max_rpm`: returns the device specific maximum target speed (i.e. hardware limits)
        `_get_shake_min_rpm`: returns the device specific minimum target speed (i.e. hardware limits)
        `_get_shake_remaining_time`: returns the remaining shake runtime in seconds when available
        `_get_shake_speed_limit_max`: returns the upper limit for the target speed
        `_get_shake_speed_limit_min`: returns the lower limit for the target speed
        `_get_shake_state`: returns shaker state as an integer
        `_get_shake_state_as_string`: returns shaker state as a string
        `_get_shake_target_speed`: returns the target mixing speed
        `_set_shake_acceleration`: sets the acceleration/deceleration value in seconds
        `_set_shake_default_direction`: permanently sets the default mixing direction after device start up
        `_set_shake_direction`: sets the mixing direction
        `_set_shake_speed_limit_max`: permanently set upper limit for the target speed (between 0 to 3000)
        `_set_shake_speed_limit_min`: permanently set lower limit for the target speed (between 0 to 3000)
        `_set_shake_target_speed`: set the target mixing speed
        `_shake_emergency_off`: stop the shaker immediately at an undefined position ignoring the defined deceleration time
        `_shake_off`: stops shaking within the defined deceleration time, go to the home position and locks in place
        `_shake_on`: starts shaking with defined speed with defined acceleration time
        `shake`: shakes at the requested speed for the requested duration in seconds
    
    #### Temperature
        `_get_temp_40_calibr`: returns the offset value at the 40°C calibration point
        `_get_temp_90_calibr`: returns the offset value at the 90°C calibration point
        `get_temp_actual`: returns the current temperature in degrees celsius
        `_get_temp_limiter_max`: returns the upper limit for the target temperature in celsius
        `_get_temp_limiter_min`: returns the lower limit for the target temperature in celsius
        `_get_temp_max`: returns the device specific maximum target temperature in celsius (i.e. hardware limits)
        `_get_temp_min`: returns the device specific minimum target temperature in celsius (i.e. hardware limits)
        `_get_temp_state`: returns the state of the temperature control feature
        `_get_temp_target`: returns the target temperature
        `_set_temp_40_calibr`: permanently sets the offset value at the 40°C calibration point in 1/10°C increments
        `_set_temp_90_calibr`: permanently sets the offset value at the 90°C calibration point in 1/10°C increments
        `_set_temp_limiter_max`: permanently sets the upper limit for the target temperature in 1/10°C increments
        `_set_temp_limiter_min`: permanently sets the lower limit for the target temperature in 1/10°C increments
        `_set_temp_target`: sets target temperature between TempMin and TempMax in 1/10°C increments
        `temp_off`: switches off the temperature control feature and stops heating/cooling
        `_temp_on`: switches on the temperature control feature and starts heating/cooling
        `set_temp`: sets, monitors, and holds a target temperature for a fixed duration
    
    #### Clamp
        `_get_elm_selftest`: returns whether the clamp self-test is enabled or disabled at device startup
        `_get_elm_startup_position`: returns whether the clamp is unlocked after device startup
        `_get_elm_state`: returns the clamp status
        `_get_elm_state_as_string`: returns the clamp status as a string
        `close_clamp`: close the clamp
        `_set_elm_selftest`: permanently set whether the clamp self-test is enabled at device startup
        `_set_elm_startup_position`: permanently set whether the clamp is unlocked after device startup
        `open_clamp`: open the clamp
    """
    
    _default_flags: SimpleNamespace = SimpleNamespace(verbose=False, connected=False, simulation=False)
    def __init__(self,
        port: str|None = None, 
        baudrate: int = 9600, 
        timeout: int = 1, 
        *,
        init_timeout: int = 5, 
        data_type: NamedTuple = Data,
        read_format: str = READ_FORMAT,
        write_format: str = WRITE_FORMAT,
        simulation: bool = False, 
        verbose: bool = False,
        **kwargs
    ):
        """
        Initialize QInstrumentsDevice class

        Args:
            port (str|None, optional): serial port for the device. Defaults to None.
            baudrate (int, optional): baudrate for the device. Defaults to 9600.
            timeout (int, optional): timeout for the device. Defaults to 1.
            init_timeout (int, optional): timeout for initialization. Defaults to 5.
            data_type (NamedTuple, optional): data type for data. Defaults to Data.
            read_format (str, optional): format for reading data. Defaults to READ_FORMAT.
            write_format (str, optional): format for writing data. Defaults to WRITE_FORMAT.
            simulation (bool, optional): whether to simulate the device. Defaults to False.
            verbose (bool, optional): verbosity of class. Defaults to False.
        """
        super().__init__(
            port=port, baudrate=baudrate, timeout=timeout,
            init_timeout=init_timeout, simulation=simulation, verbose=verbose, 
            data_type=data_type, read_format=read_format, write_format=write_format, **kwargs
        )
        
        self.model = ''
        self.serial_number = ''
        self.connect()
    
    # General methods
    def connect(self):
        super().connect()
        if self.check_device_connection():
            self.model = self._query("getDescription").data
            self.serial_number = self._query("getSerial").data
    
    def _query(self, 
        data: Any, 
        multi_out: bool = False,
        *,
        timeout: int|float = 0.3,
        format_in: str|None = None, 
        format_out: str|None = None,
        data_type: NamedTuple|None = None,
        timestamp: bool = False
    ) -> Any:
        """
        Query the device (i.e. write and read data)

        Args:
            data (Any): data to write to the device
            multi_out (bool, optional): whether to expect multiple outputs. Defaults to False.
            timeout (int|float, optional): timeout for the query. Defaults to 0.3.
            format_in (str|None, optional): format for writing data. Defaults to None.
            format_out (str|None, optional): format for reading data. Defaults to None.
            data_type (NamedTuple|None, optional): data type for data. Defaults to None.
            timestamp (bool, optional): whether to include a timestamp. Defaults to False.
        
        Returns:
            str|float|None: response (string / float)
        """
        data_type: NamedTuple = data_type or self.data_type
        format_in = format_in or self.write_format
        format_out = format_out or self.read_format
        if self.flags.simulation:
            field_types = data_type.__annotations__
            signature = inspect.signature(data_type)
            defaults = [
                parameter.default
                if parameter.default is not inspect.Signature.empty
                else ("" if field_types[field_name] is str else field_types[field_name](0))
                for field_name, parameter in signature.parameters.items()
            ]
            data_out = data_type(*defaults)
            response = (data_out, datetime.now()) if timestamp else data_out
            return [response] if multi_out else response
        
        responses = super().query(
            data, multi_out=multi_out, timeout=timeout,
            format_in=format_in, timestamp=timestamp
        )
        self._logger.debug(repr(responses))
        if multi_out and not responses:
            return None
        responses = responses if multi_out else [responses]
        
        all_output = []
        for response in responses:
            now = None
            if timestamp:
                out,now = response
            else:
                out = response
            if out is None:
                all_output.append(response)
                continue
            out: Data = out
            # Check invalid commands
            if isinstance(out.data, str) and out.data.startswith('u ->'):
                error_message = f"{self.model} received an invalid command: {data!r}"
                self._logger.error(error_message)
                self.clear_device_buffer()
                raise AttributeError(error_message)
            
            data_out = self.process_output(out.data, format_out=format_out, data_type=data_type)
            data_out = data_out if timestamp else data_out[0]
            
            all_output.append((data_out, now) if timestamp else data_out)
        return all_output if multi_out else all_output[0]

    # ECO methods
    def _leave_eco_mode(self, timeout:int = 5):
        """
        Leaves the economical mode and switches into the normal operating state
        
        Args:
            timeout (int, optional): number of seconds to wait before aborting. Defaults to 5.
        """
        self._query("leaveEcoMode")
        start_time = time.perf_counter()
        while self._get_shake_state() != 3:
            time.sleep(0.1)
            if time.perf_counter() - start_time > timeout:
                break
        self._get_shake_state()
        return
    
    def _set_eco_mode(self, timeout:int = 5):
        """
        Switches the shaker into economical mode and reduces electricity consumption.
        
        Note: all commands after this, other than `_leave_eco_mode`, will return `e`
        
        Args:
            timeout (int, optional): number of seconds to wait before aborting. Defaults to 5.
        """
        self._query("setEcoMode", timeout=timeout)
        return
        
    # Shaking methods
    def _get_shake_acceleration(self) -> float|None:
        """
        Returns the acceleration/deceleration value

        Returns:
            float|None: acceleration/deceleration value
        """
        out: FloatData = self._query("getShakeAcceleration", data_type=FloatData)
        return out.data
        
    def _get_shake_acceleration_max(self) -> float|None:
        """
        Get the maximum acceleration/deceleration time in seconds

        Returns:
            float|None: acceleration/deceleration time in seconds
        """
        out: FloatData = self._query("getShakeAccelerationMax", data_type=FloatData)
        return out.data if out.data > 0 else 999999
    
    def _get_shake_acceleration_min(self) -> float|None:
        """
        Get the minimum acceleration/deceleration time in seconds

        Returns:
            float|None: acceleration/deceleration time in seconds
        """
        out: FloatData = self._query("getShakeAccelerationMin", data_type=FloatData)
        return out.data
    
    def _get_shake_actual_speed(self) -> float|None:
        """
        Returns the current mixing speed

        Returns:
            float|None: current mixing speed
        """
        out: FloatData = self._query("getShakeActualSpeed", data_type=FloatData)
        return out.data
    
    def _get_shake_default_direction(self) -> bool|None:
        """
        Returns the mixing direction when the device starts up

        Returns:
            bool|None: whether mixing direction is counterclockwise
        """
        out: BoolData = self._query("getShakeDefaultDirection", data_type=BoolData)
        return out.data
        
    def _get_shake_direction(self) -> bool|None:
        """
        Returns the current mixing direction

        Returns:
            bool|None: whether mixing direction is counterclockwise
        """
        out: BoolData = self._query("getShakeDirection", data_type=BoolData)
        return out.data
        
    def _get_shake_max_rpm(self) -> float|None:
        """
        Returns the device specific maximum target speed (i.e. hardware limits)

        Returns:
            float|None: maximum target shake speed
        """
        out: FloatData = self._query("getShakeMaxRpm", data_type=FloatData)
        return out.data
    
    def _get_shake_min_rpm(self) -> float|None:
        """
        Returns the device specific minimum target speed (i.e. hardware limits)

        Returns:
            float|None: minimum target shake speed
        """
        out: FloatData = self._query("getShakeMinRpm", data_type=FloatData)
        return out.data
    
    def _get_shake_remaining_time(self) -> float|None:
        """
        Returns the remaining shake runtime in seconds when available

        Returns:
            float|None: minimum target shake speed
        """
        out: FloatData = self._query("getShakeRemainingTime", data_type=FloatData)
        return out.data
    
    def _get_shake_speed_limit_max(self) -> float|None:
        """
        Returns the upper limit for the target speed

        Returns:
            float|None: upper limit for the target speed
        """
        out: FloatData = self._query("getShakeSpeedLimitMax", data_type=FloatData)
        return out.data
    
    def _get_shake_speed_limit_min(self) -> float|None:
        """
        Returns the lower limit for the target speed

        Returns:
            float|None: lower limit for the target speed
        """
        out: FloatData = self._query("getShakeSpeedLimitMin", data_type=FloatData)
        return out.data
    
    def _get_shake_state(self) -> int|None:
        """
        Returns shaker state as an integer
        
        Returns:
            int|None: shaker state as integer
        """
        out: IntData = self._query("getShakeState", data_type=IntData)
        code = f"ss{out.data}"
        if code in ShakeStateCode.__members__:
            self._logger.info(ShakeStateCode[code].value)
        return out.data
        
    def _get_shake_state_as_string(self) -> str|None:
        """
        Returns shaker state as a string
        
        Returns:
            str|None: shaker state as string
        """
        out: Data = self._query("getShakeStateAsString")
        code = out.data.replace("+","t").replace("-","_")
        if code in ShakeStateString.__members__:
            self._logger.info(ShakeStateString[code].value)
        return out.data
        
    def _get_shake_target_speed(self) -> float|None:
        """
        Returns the target mixing speed

        Returns:
            float|None: target mixing speed
        """
        out: FloatData = self._query("getShakeTargetSpeed", data_type=FloatData)
        return out.data
    
    def _set_shake_acceleration(self, acceleration:int):
        """
        Sets the acceleration/deceleration value in seconds

        Args:
            acceleration (int): acceleration value
        """
        self._query(f"setShakeAcceleration{int(acceleration)}")
        return
    
    def _set_shake_default_direction(self, counterclockwise:bool):
        """
        Permanently sets the default mixing direction after device start up

        Args:
            counterclockwise (bool): whether to set default mixing direction to counter clockwise
        """
        self._query(f"setShakeDefaultDirection{int(counterclockwise)}")
        return
    
    def _set_shake_direction(self, counterclockwise:bool):
        """
        Sets the mixing direction

        Args:
            counterclockwise (bool): whether to set mixing direction to counter clockwise
        """
        self._query(f"setShakeDirection{int(counterclockwise)}")
        return
    
    def _set_shake_speed_limit_max(self, speed:int):
        """
        Permanently set upper limit for the target speed (between 0 to 3000)

        Args:
            speed (int): upper limit for the target speed
        """
        self._query(f"setShakeSpeedLimitMax{int(speed)}")
        return
    
    def _set_shake_speed_limit_min(self, speed:int):
        """
        Permanently set lower limit for the target speed (between 0 to 3000)
        
        Note: Speed values below 200 RPM are possible, but not recommended

        Args:
            speed (int): lower limit for the target speed
        """
        self._query(f"setShakeSpeedLimitMin{int(speed)}")
        return
        
    def _set_shake_target_speed(self, speed:int):
        """
        Set the target mixing speed
        
        Note: Speed values below 200 RPM are possible, but not recommended

        Args:
            speed (int): target mixing speed
        """
        self._query(f"setShakeTargetSpeed{int(speed)}")
        return
        
    def _shake_emergency_off(self):
        """Stop the shaker immediately at an undefined position ignoring the defined deceleration time"""
        self._query("shakeEmergencyOff")
        return
        
    def home(self, timeout:int = 5):
        """
        Move shaker to the home position and locks in place
        
        Note: Minimum response time is less than 4 sec (internal failure timeout)
        
        Args:
            timeout (int, optional): number of seconds to wait before aborting. Defaults to 5.
        """
        self._query("shakeGoHome")
        start_time = time.perf_counter()
        while self._get_shake_state() != 3:
            time.sleep(0.1)
            if time.perf_counter() - start_time > timeout:
                break
        self._get_shake_state()
        return
        
    def _shake_off(self):
        """Stops shaking within the defined deceleration time, go to the home position and locks in place"""
        self._query("shakeOff")
        while self._get_shake_state() != 3:
            time.sleep(0.1)
        self._get_shake_state()
        return
        
    def _shake_on(self):
        """Starts shaking with defined speed with defined acceleration time"""
        self._query("shakeOn")
        return

    def shake(self, speed:int, duration:int):
        """
        Shake at the requested speed for the requested duration in seconds,
        then stop the shaker.

        Args:
            speed (int): target shake speed in RPM
            duration (int): shake duration in seconds
        """
        if duration < 0:
            raise ValueError("Duration must be greater than or equal to 0 seconds.")

        min_speed = self._get_shake_min_rpm()
        if min_speed is not None and speed < min_speed:
            raise ValueError(
                f"Target speed {speed} RPM is below the device minimum of {min_speed:.1f} RPM."
            )

        max_speed = self._get_shake_max_rpm()
        if max_speed is not None and speed > max_speed:
            raise ValueError(
                f"Target speed {speed} RPM is above the device maximum of {max_speed:.1f} RPM."
            )

        speed_limit_min = self._get_shake_speed_limit_min()
        if speed_limit_min is not None and speed < speed_limit_min:
            raise ValueError(
                f"Target speed {speed} RPM is below the configured minimum limit of {speed_limit_min:.1f} RPM."
            )

        speed_limit_max = self._get_shake_speed_limit_max()
        if speed_limit_max is not None and speed > speed_limit_max:
            raise ValueError(
                f"Target speed {speed} RPM is above the configured maximum limit of {speed_limit_max:.1f} RPM."
            )

        target_speed = int(speed)
        self._logger.info("Setting target speed to %d RPM", target_speed)
        self._set_shake_target_speed(target_speed)

        configured_speed = self._get_shake_target_speed()
        if configured_speed is None:
            raise RuntimeError("BioShake did not report a target shake speed")
        if abs(configured_speed - target_speed) > 0.1:
            raise RuntimeError(
                f"Expected target speed {target_speed} RPM, got {configured_speed:.1f} RPM"
            )

        shake_started = False
        try:
            self._logger.info("Starting shake for %d seconds", duration)
            self._shake_on()
            shake_started = True
            time.sleep(duration)
        finally:
            if shake_started:
                self._logger.info("Stopping shaker")
                self._shake_off()

        return
    
    # Temperature methods
    def _get_temp_40_calibr(self) -> float|None:
        """
        Returns the offset value at the 40°C calibration point

        Returns:
            float|None: offset value at the 40°C calibration point
        """
        out: FloatData = self._query("getTemp40Calibr", data_type=FloatData)
        return out.data
    
    def _get_temp_90_calibr(self) -> float|None:
        """
        Returns the offset value at the 90°C calibration point

        Returns:
            float|None: offset value at the 90°C calibration point
        """
        out: FloatData = self._query("getTemp90Calibr", data_type=FloatData)
        return out.data
    
    def get_temp_actual(self) -> float|None:
        """
        Returns the current temperature in degrees celsius

        Returns:
            float|None: current temperature in degrees celsius
        """
        out: FloatData = self._query("getTempActual", data_type=FloatData)
        return out.data
        
    def _get_temp_limiter_max(self) -> float|None:
        """
        Returns the upper limit for the target temperature in celsius

        Returns:
            float|None: upper limit for the target temperature in celsius
        """
        out: FloatData = self._query("getTempLimiterMax", data_type=FloatData)
        return out.data
    
    def _get_temp_limiter_min(self) -> float|None:
        """
        Returns the lower limit for the target temperature in celsius

        Returns:
            float|None: lower limit for the target temperature in celsius
        """
        out: FloatData = self._query("getTempLimiterMin", data_type=FloatData)
        return out.data
    
    def _get_temp_max(self) -> float|None:
        """
        Returns the device specific maximum target temperature in celsius (i.e. hardware limits)

        Returns:
            float|None: device specific maximum target temperature in celsius
        """
        out: FloatData = self._query("getTempMax", data_type=FloatData)
        return out.data
    
    def _get_temp_min(self) -> float|None:
        """
        Returns the device specific minimum target temperature in celsius (i.e. hardware limits)

        Returns:
            float|None: device specific minimum target temperature in celsius
        """
        out: FloatData = self._query("getTempMin", data_type=FloatData)
        return out.data
    
    def _get_temp_state(self) -> bool:
        """
        Returns the state of the temperature control feature

        Returns:
            bool: whether temperature control is enabled
        """
        out: BoolData = self._query("getTempState", data_type=BoolData)
        return out.data
    
    def _get_temp_target(self) -> float|None:
        """
        Returns the target temperature

        Returns:
            float|None: target temperature
        """
        out: FloatData = self._query("getTempTarget", data_type=FloatData)
        return out.data
        
    def _set_temp_40_calibr(self, temperature_calibration_40:float):
        """
        Permanently sets the offset value at the 40°C calibration point in 1/10°C increments

        Args:
            temperature_calibration_40 (float): offset value (between 0°C and 99°C)
        """
        value = int(temperature_calibration_40*10)
        self._query(f"setTemp40Calibr{value}")
        return
    
    def _set_temp_90_calibr(self, temperature_calibration_90:float):
        """
        Permanently sets the offset value at the 90°C calibration point in 1/10°C increments

        Args:
            temperature_calibration_90 (float): offset value (between 0°C and 99°C)
        """
        value = int(temperature_calibration_90*10)
        self._query(f"setTemp90Calibr{value}")
        return
    
    def _set_temp_limiter_max(self, temperature_max:float):
        """
        Permanently sets the upper limit for the target temperature in 1/10°C increments

        Args:
            temperature_max (float): upper limit for the target temperature (between -20.0°C and 99.9°C)
        """
        value = int(temperature_max*10)
        self._query(f"setTempLimiterMax{value}")
        return
    
    def _set_temp_limiter_min(self, temperature_min:float):
        """
        Permanently sets the lower limit for the target temperature in 1/10°C increments

        Args:
            temperature_min (float): lower limit for the target temperature (between -20.0°C and 99.9°C)
        """
        value = int(temperature_min*10)
        self._query(f"setTempLimiterMin{value}")
        return
    
    def _set_temp_target(self, temperature:float):
        """
        Sets target temperature between TempMin and TempMax in 1/10°C increments

        Args:
            temperature (float): target temperature (between TempMin and TempMax)
        """
        value = int(temperature*10)
        self._query(f"setTempTarget{value}")
        return
    
    def temp_off(self):
        """Switches off the temperature control feature and stops heating/cooling"""
        self._query("tempOff")
        return
    
    def _temp_on(self):
        """Switches on the temperature control feature and starts heating/cooling"""
        self._query("tempOn")
        return

    def set_temp(self, temperature:int, duration:int):
        """
        Set the target temperature, wait until it is reached within tolerance,
        and hold it for the requested duration in seconds.

        Args:
            temperature (int): target temperature in celsius
            duration (int): hold duration in seconds
        """
        if duration < 0:
            raise ValueError("Duration must be greater than or equal to 0 seconds.")

        min_temp = self._get_temp_min()
        if min_temp is not None and temperature < min_temp:
            raise ValueError(
                f"Target temperature {temperature} C is below the device minimum of {min_temp:.1f} C."
            )

        max_temp = self._get_temp_max()
        if max_temp is not None and temperature > max_temp:
            raise ValueError(
                f"Target temperature {temperature} C is above the device maximum of {max_temp:.1f} C."
            )

        target_temp = float(temperature)
        temperature_tolerance_c = 5.0
        poll_interval_seconds = 0.5
        hold_started_at: float | None = None
        temp_enabled = False

        self._logger.info("Setting target temperature to %.1f C", target_temp)
        self._set_temp_target(target_temp)

        configured_temp = self._get_temp_target()
        if configured_temp is None:
            raise RuntimeError("BioShake did not report a target temperature")
        if abs(configured_temp - target_temp) > 0.1:
            raise RuntimeError(
                f"Expected target temperature {target_temp:.1f} C, got {configured_temp:.1f} C"
            )

        try:
            self._logger.info("Enabling temperature control")
            self._temp_on()
            temp_enabled = True

            while True:
                actual_temp = self.get_temp_actual()
                if actual_temp is None:
                    raise RuntimeError("BioShake did not report an actual temperature")

                self._logger.info(
                    "Temperature status: actual=%.1f C target=%.1f C",
                    actual_temp,
                    configured_temp,
                )

                if abs(actual_temp - configured_temp) <= temperature_tolerance_c:
                    if hold_started_at is None:
                        hold_started_at = time.perf_counter()
                        self._logger.info(
                            "Temperature is within %.1f C of target; holding for %d seconds",
                            temperature_tolerance_c,
                            duration,
                        )

                    if time.perf_counter() - hold_started_at >= duration:
                        break
                elif hold_started_at is not None:
                    raise RuntimeError(
                        "Temperature drifted outside the allowed "
                        f"{temperature_tolerance_c:.1f} C tolerance while holding the target"
                    )

                time.sleep(poll_interval_seconds)
        finally:
            if temp_enabled:
                self._logger.info("Disabling temperature control")
                self.temp_off()

        self._logger.info(
            "Maintained target temperature %.1f C for %d seconds",
            configured_temp,
            duration,
        )
        return
    
    # Clamp methods
    def _get_elm_selftest(self) -> bool:
        """
        Returns whether the clamp self-test is enabled or disabled at device startup

        Returns:
            bool: whether the clamp self-test is enabled at device startup
        """
        out: BoolData = self._query("getElmSelftest", data_type=BoolData)
        return out.data
        
    def _get_elm_startup_position(self) -> bool:
        """
        Returns whether the clamp is unlocked after device startup

        Returns:
            bool: whether the clamp is unlocked after device startup
        """
        out: BoolData = self._query("getElmStartupPosition", data_type=BoolData)
        return out.data
    
    def _get_elm_state(self) -> int|None:
        """
        Returns the clamp status
        
        Returns:
            int|None: clamp status as integer
        """
        out: IntData = self._query("getElmState", data_type=IntData)
        code = f"es{out.data}"
        if code in ELMStateCode.__members__:
            self._logger.info(ELMStateCode[code].value)
        return out.data
    
    def _get_elm_state_as_string(self) -> str|None:
        """
        Returns the clamp status as a string
        
        Returns:
            str|None: clamp status as string
        """
        out: Data = self._query("getElmStateAsString")
        if out.data in ELMStateString.__members__:
            self._logger.info(ELMStateString[out.data].value)
        return out.data
    
    def close_clamp(self, timeout:int = 5) -> bool:
        """
        Close the clamp
        
        Args:
            timeout (int, optional): number of seconds to wait before aborting. Defaults to 5.
        
        Returns:
            bool: whether the clamp was successfully closed
        """
        out = self._query("setElmLockPos", timeout=timeout)
        while out is None:
            if self.flags.simulation:
                break
            out = self.read().strip()
        if out == 'ok':
            return True
        return False
    
    def _set_elm_selftest(self, enable:bool):
        """
        Permanently set whether the clamp self-test is enabled at device startup

        Args:
            enable (bool): whether the clamp self-test is enabled at device startup
        """
        self._query(f"setElmSelftest{int(enable)}")
        return
        
    def _set_elm_startup_position(self, unlock:bool):
        """
        Permanently set whether the clamp is unlocked after device startup

        Args:
            unlock (bool): whether the clamp is unlocked after device startup
        """
        self._query(f"setElmStartupPosition{int(unlock)}")
        return
    
    def open_clamp(self, timeout:int = 5) -> bool:
        """
        Open the clamp
        
        Note: The clamp should only be opened when the tablar is in the home position.
        
        Args:
            timeout (int, optional): number of seconds to wait before aborting. Defaults to 5.
        
        Returns:
            bool: whether the clamp was successfully opened
        """
        out = self._query("setElmUnlockPos", timeout=timeout)
        while out is None:
            if self.flags.simulation:
                break
            out = self.read().strip()
        if out == 'ok':
            return True
        return False

 