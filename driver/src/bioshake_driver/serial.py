# -*- coding: utf-8 -*-
"""
This module provides base classes for serial device connections.

Attributes:
    READ_FORMAT (str): default read format for device connections
    WRITE_FORMAT (str): default write format for device connections
    Data (NamedTuple): default data type for device connections

## Classes:
    `BaseDevice`: Base class for device connections
    `SerialDevice`: Class for serial device connections
"""
# Standard library imports
from __future__ import annotations
from collections import deque
from copy import deepcopy
from datetime import datetime
import logging
import queue
from string import Formatter
import threading
import time
from types import SimpleNamespace
from typing import Any, NamedTuple, Callable

# Third party imports
import parse
import serial

logger = logging.getLogger(__name__)

READ_FORMAT = "{data}\n"
WRITE_FORMAT = "{data}\n"
Data = NamedTuple("Data", [("data", str)])


class BaseDevice:
    """
    BaseDevice provides an interface for handling device connections
    
    ### Constructor:
        `connection_details` (dict|None, optional): connection details for the device. Defaults to None.
        `init_timeout` (int, optional): timeout for initialization. Defaults to 1.
        `data_type` (NamedTuple, optional): data type for the device. Defaults to Data.
        `read_format` (str, optional): read format for the device. Defaults to READ_FORMAT.
        `write_format` (str, optional): write format for the device. Defaults to WRITE_FORMAT.
        `simulation` (bool, optional): whether to simulate the device. Defaults to False.
        `verbose` (bool, optional): verbosity of class. Defaults to False.
        
    ### Attributes and properties:
        `connection` (Any|None): connection object for the device
        `connection_details` (dict): connection details for the device
        `flags` (SimpleNamespace[str, bool]): flags for the device
        `init_timeout` (int): timeout for initialization
        `data_type` (NamedTuple): data type for the device
        `read_format` (str): read format for the device
        `write_format` (str): write format for the device
        `eol` (str): end of line character for the read format
        `buffer` (deque): buffer for storing streamed data
        `data_queue` (queue.Queue): queue for storing processed data
        `show_event` (threading.Event): event for showing streamed data
        `stream_event` (threading.Event): event for controlling streaming
        `threads` (dict): dictionary of threads used in streaming
        
    ### Methods:
        `clear`: clear the input and output buffers, and reset the data queue and buffer
        `connect`: connect to the device
        `disconnect`: disconnect from the device
        `check_device_connection`: check the connection to the device
        `check_device_buffer`: check the connection buffer
        `clear_device_buffer`: clear the device input and output buffers
        `read`: read data from the device
        `read_all`: read all data from the device
        `write`: write data to the device
        `poll`: poll the device (i.e. write and read data)
        `process_input`: process the input data
        `process_output`: process the output data
        `query`: query the device (i.e. write and read data)
        `start_stream`: start the stream
        `stop_stream`: stop the stream
        `stream`: toggle the stream
        `show_stream`: show the stream
    """
    
    _default_flags: SimpleNamespace = SimpleNamespace(verbose=False, connected=False, simulation=False)
    def __init__(self, 
        *, 
        connection_details:dict|None = None, 
        init_timeout:int = 1, 
        data_type: NamedTuple =  Data,
        read_format:str = READ_FORMAT,
        write_format:str = WRITE_FORMAT,
        simulation:bool = False, 
        verbose:bool = False, 
        **kwargs
    ):
        """
        Initialize BaseDevice class
        
        Args:
            connection_details (dict|None, optional): connection details for the device. Defaults to None.
            init_timeout (int, optional): timeout for initialization. Defaults to 1.
            data_type (NamedTuple, optional): data type for the device. Defaults to Data.
            read_format (str, optional): read format for the device. Defaults to READ_FORMAT.
            write_format (str, optional): write format for the device. Defaults to WRITE_FORMAT.
            simulation (bool, optional): whether to simulate the device. Defaults to False.
            verbose (bool, optional): verbosity of class. Defaults to False.
        """
        # Connection attributes
        self.connection: Any|None = None
        self.connection_details = dict() if connection_details is None else connection_details
        self.flags = deepcopy(self._default_flags)
        self.init_timeout = init_timeout
        self.flags.simulation = simulation
        
        # IO attributes
        self.data_type = data_type
        self.read_format = read_format
        self.write_format = write_format
        self.eol = self.read_format.replace(self.read_format.rstrip(), '')
        fields = set([field for _, field, _, _ in Formatter().parse(read_format) if field and not field.startswith('_')])
        assert set(data_type._fields) == fields, "Ensure data type fields match read format fields"
        
        # Streaming attributes
        self.buffer = deque()
        self.data_queue = queue.Queue()
        self.show_event = threading.Event()
        self.stream_event = threading.Event()
        self.threads = dict()
        
        # Logging attributes
        self._logger = logger.getChild(f"{self.__class__.__name__}.{id(self)}")
        self.verbose = verbose
        return
    
    def __del__(self):
        self.disconnect()
        return
    
    def __enter__(self):
        """Context manager enter method"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        """Context manager exit method"""
        self.disconnect()
        return False
    
    @property
    def is_connected(self) -> bool:
        """Whether the device is connected"""
        connected = self.flags.connected if self.flags.simulation else self.check_device_connection()
        return connected
    
    @property
    def verbose(self) -> bool:
        """Verbosity of class"""
        return self.flags.verbose
    @verbose.setter
    def verbose(self, value:bool):
        assert isinstance(value,bool), "Ensure assigned verbosity is boolean"
        self.flags.verbose = value
        level = logging.DEBUG if value else logging.INFO
        self._logger.setLevel(level)
        return
    
    # Connection methods
    def check_device_connection(self) -> bool:
        """
        Check the connection to the device
        
        Returns:
            bool: whether the device is connected
        """
        if hasattr(self.connection, 'is_open'):
            return self.connection.is_open()
        return self.flags.connected

    def connect(self):
        """Connect to the device"""
        if self.is_connected:
            return
        connection_details = repr(self.connection_details) if self.connection_details else '{...}'
        try:
            self.connection.open()
        except Exception as e:
            self._logger.error(f"Failed to connect to {connection_details}")
            self._logger.debug(e)
        else:
            self._logger.info(f"Connected to {connection_details}")
            time.sleep(self.init_timeout)
        self.flags.connected = True
        return

    def disconnect(self):
        """Disconnect from the device"""
        if not self.is_connected:
            return
        self.stop_stream()
        connection_details = repr(self.connection_details) if self.connection_details else '{...}'
        try:
            self.connection.close()
        except Exception as e:
            self._logger.error(f"Failed to disconnect from {connection_details}")
            self._logger.debug(e)
        else:
            self._logger.info(f"Disconnected from {connection_details}")
        self.flags.connected = False
        return
    
    # IO methods
    def check_device_buffer(self) -> bool:
        """
        Check the connection buffer
        
        Returns:
            bool: whether there is data in the connection buffer
        """
        return self.connection.in_waiting()
    
    def clear_device_buffer(self):
        """Clear the device input and output buffers"""
        ...
        return
    
    def clear(self):
        """Clear the input and output buffers, and reset the data queue and buffer"""
        self.stop_stream()
        self.buffer = deque()
        self.data_queue = queue.Queue()
        if self.flags.simulation:
            return
        self.clear_device_buffer()
        return

    def read(self) -> str:
        """
        Read data from the device
        
        Returns:
            str|None: data read from the device
        """
        data = ''
        try:
            data = self.connection.read().decode("utf-8", "replace")
            data = data.strip()
            self._logger.debug(f"Received: {data!r}")
        except Exception:
            self._logger.debug("Failed to receive data")
        except KeyboardInterrupt:
            self._logger.debug("Received keyboard interrupt")
            self.disconnect()
        return data
    
    def read_all(self) -> list[str]:
        """
        Read all data from the device
        
        Returns:
            list[str]|None: data read from the device
        """
        delimiter = self.eol
        data = ''
        try:
            while True:
                out = self.connection.read_all().decode("utf-8", "replace")
                data += out
                if not out:
                    break
        except Exception as e:
            self._logger.debug("Failed to receive data")
            self._logger.debug(e)
        except KeyboardInterrupt:
            self._logger.debug("Received keyboard interrupt")
            self.disconnect()
        data = data.strip()
        self._logger.debug(f"Received: {data!r}")
        return [d for d in data.split(delimiter) if len(d)]
    
    def write(self, data:str) -> bool:
        """
        Write data to the device
        
        Args:
            data (str): data to write to the device
            
        Returns:
            bool: whether the data was written successfully
        """
        assert isinstance(data, str), "Ensure data is a string"
        try:
            self.connection.write(data.encode('utf-8'))
            self._logger.debug(f"Sent: {data!r}")
        except Exception:
            self._logger.debug(f"Failed to send: {data!r}")
            return False
        return True
    
    def poll(self, data:str|None = None) -> str:
        """
        Poll the device
        
        Args:
            data (str|None, optional): data to write to the device. Defaults to None.
            
        Returns:
            str|None: data read from the device
        """
        out = ''
        ret = True
        if data is not None:
            ret = self.write(data)
        if data is None or ret:
            out: str = self.read()
        return out
    
    def process_input(self, 
        data: Any = None,
        format_in: str|None = None,
        **kwargs
    ) -> str|None:
        """
        Process the input
        
        Args:
            data (Any, optional): data to process. Defaults to None.
            format_in (str|None, optional): format for the data. Defaults to None.
            
        Returns:
            str|None: processed input data
        """
        if data is None:
            return None
        format_in = format_in or self.write_format
        assert isinstance(format_in, str), "Ensure format is a string"
        
        kwargs.update(dict(data=data))
        processed_data = format_in.format(**kwargs)
        return processed_data
    
    def process_output(self, 
        data: str, 
        format_out: str|None = None, 
        data_type: NamedTuple|None = None, 
        timestamp: datetime|None = None
    ) -> tuple[Any, datetime|None]:
        """
        Process the output
        
        Args:
            data (str): data to process
            format_out (str|None, optional): format for the data. Defaults to None.
            data_type (NamedTuple|None, optional): data type for the data. Defaults to None.
            timestamp (datetime|None, optional): timestamp for the data. Defaults to None.
            
        Returns:
            tuple[Any, datetime|None]: processed output data and timestamp
        """
        format_out = format_out or self.read_format
        format_out = format_out.strip()
        data_type = data_type or self.data_type
        fields = set([field for _, field, _, _ in Formatter().parse(format_out) if field and not field.startswith('_')])
        assert set(data_type._fields) == fields, "Ensure data type fields match read format fields"
        
        try:
            parse_out = parse.parse(format_out, data)
        except TypeError:
            if data:
                self._logger.warning(f"Failed to parse data: {data!r}")
            return None, timestamp
        if parse_out is None:
            if data:
                self._logger.warning(f"Failed to parse data: {data!r}")
            return None, timestamp
        parsed = {k:v for k,v in parse_out.named.items() if not k.startswith('_')}
        for key, value in data_type.__annotations__.items():
            try:
                if value is int and not parsed[key].isnumeric():
                    parsed[key] = float(parsed[key])
                elif value is bool:
                    parsed[key] = parsed[key].lower() not in ['false', '0', 'no']
                parsed[key] = value(parsed[key])
            except ValueError:
                self._logger.warning(f"Failed to convert {key}: {parsed[key]} to type {value}")
                return None ,timestamp
        processed_data = data_type(**parsed) 
        
        if self.show_event.is_set():
            print(processed_data)
        return processed_data, timestamp
    
    def query(self, 
        data: Any, 
        multi_out: bool = True,
        *, 
        timeout: int|float = 1,
        format_in: str|None = None, 
        format_out: str|None = None,
        data_type: NamedTuple|None = None,
        timestamp: bool = False,
        **kwargs
    ) -> Any | None:
        """
        Query the device
        
        Args:
            data (Any): data to query
            multi_out (bool, optional): whether to return multiple outputs. Defaults to True.
            timeout (int|float, optional): timeout for the query. Defaults to 1.
            format_in (str|None, optional): format for the input data. Defaults to None.
            format_out (str|None, optional): format for the output data. Defaults to None.
            data_type (NamedTuple|None, optional): data type for the data. Defaults to None.
            timestamp (bool, optional): whether to return the timestamp. Defaults to False.
            
        Returns:
            Any|None: queried data
        """
        data_type: NamedTuple = data_type or self.data_type
        data_in = self.process_input(data, format_in, **kwargs)
        now = datetime.now() if timestamp else None
        if not multi_out:
            raw_out = self.poll(data_in)
            if raw_out == '':
                return (None, now) if timestamp else None
            out, now = self.process_output(raw_out, format_out, data_type, now)
            return (out, now) if timestamp else out
        
        all_data = []
        ret = self.write(data_in) if data_in is not None else True
        if not ret:
            return all_data
        start_time = time.perf_counter()
        while True:
            if time.perf_counter() - start_time > timeout:
                break
            raw_out = self.read_all()
            now = datetime.now() if timestamp else None
            start_time = time.perf_counter()
            
            processed_out = [self.process_output(out, format_out, data_type, now) for out in raw_out]
            processed_out = [(out, now) for out, now in processed_out if out is not None]
            all_data.extend([(out, now) if timestamp else out for out,now in processed_out])
            if not self.check_device_buffer():
                break
        return all_data

    # Streaming methods
    def show_stream(self, on: bool):
        """
        Show the stream
        
        Args:
            on (bool): whether to show the stream
        """
        _ = self.show_event.set() if on else self.show_event.clear()
        return
    
    def start_stream(self, 
        data: str|None = None, 
        buffer: deque|None = None,
        *, 
        format_out: str|None = None, 
        data_type: NamedTuple|None = None,
        show: bool = False,
        sync_start: threading.Barrier|None = None,
        split_stream: bool = True,
        callback: Callable[[str],Any]|None = None
    ):
        """
        Start the stream
        
        Args:
            data (str|None, optional): data to stream. Defaults to None.
            buffer (deque|None, optional): buffer to store the streamed data. Defaults to None.
            format_out (str|None, optional): format for the data. Defaults to None.
            data_type (NamedTuple|None, optional): data type for the data. Defaults to None.
            show (bool, optional): whether to show the stream. Defaults to False.
            sync_start (threading.Barrier|None, optional): synchronization barrier. Defaults to None.
            split_stream (bool, optional): whether to split the stream and data processing threads. Defaults to True.
            callback (Callable[[str],Any]|None, optional): callback function to call with the streamed data. Defaults to None.
        """
        sync_start = sync_start or threading.Barrier(2, timeout=2)
        assert isinstance(sync_start, threading.Barrier), "Ensure sync_start is a threading.Barrier"
        if self.stream_event.is_set():
            self.show_stream(show)
            return
        self.stream_event.set()
        if split_stream:
            self.threads['stream'] = threading.Thread(
                target=self._loop_stream, 
                args=(data,sync_start),
                kwargs=dict(callback=callback),
                daemon=True
            )
            self.threads['process'] = threading.Thread(
                target=self._loop_process_data, 
                kwargs=dict(buffer=buffer, format_out=format_out, data_type=data_type, sync_start=sync_start), 
                daemon=True
            )
        else:
            self.threads['stream'] = threading.Thread(
                target=self._loop_stream, 
                args=(data,),
                kwargs=dict(buffer=buffer, format_out=format_out, data_type=data_type, split_stream=split_stream, callback=callback), 
                daemon=True
            )
        self.show_stream(show)
        self.threads['stream'].start()
        if split_stream:
            self.threads['process'].start()
        return
    
    def stop_stream(self):
        """Stop the stream"""
        self.stream_event.clear()
        self.show_stream(False)
        for thread in self.threads.values():
            _ = thread.join() if isinstance(thread, threading.Thread) else None
        return
    
    def stream(self, 
        on:bool, 
        data: str|None = None, 
        buffer: deque|None = None, 
        *,
        sync_start:threading.Barrier|None = None,
        split_stream: bool = True,
        callback: Callable[[str],Any]|None = None,
        **kwargs
    ):
        """
        Toggle the stream
        
        Args:
            on (bool): whether to start or stop the stream
            data (str|None, optional): data to stream. Defaults to None.
            buffer (deque|None, optional): buffer to store the streamed data. Defaults to None.
            sync_start (threading.Barrier|None, optional): synchronization barrier. Defaults to None.
            split_stream (bool, optional): whether to split the stream and data processing threads. Defaults to True.
            callback (Callable[[str],Any]|None, optional): callback function to call with the streamed data. Defaults to None.
        """
        return self.start_stream(data=data, buffer=buffer, sync_start=sync_start, split_stream=split_stream, callback=callback, **kwargs) if on else self.stop_stream()
    
    def _loop_process_data(self, 
        buffer: deque|None = None,
        format_out: str|None = None, 
        data_type: NamedTuple|None = None, 
        sync_start: threading.Barrier|None = None
    ):
        """ 
        Process the data
        
        Args:
            buffer (deque|None, optional): buffer to store the streamed data. Defaults to None.
            format_out (str|None, optional): format for the data. Defaults to None.
            data_type (NamedTuple|None, optional): data type for the data. Defaults to None.
            sync_start (threading.Barrier|None, optional): synchronization barrier. Defaults to None.
        """
        if buffer is None:
            buffer = self.buffer
        assert isinstance(buffer, deque), "Ensure buffer is a deque"
        if isinstance(sync_start, threading.Barrier):
            sync_start.wait()
        
        while self.stream_event.is_set():
            try:
                out, now = self.data_queue.get(timeout=5)
                out, now = self.process_output(out, format_out=format_out, data_type=data_type, timestamp=now)
                if out is not None:
                    buffer.append((out, now))
                self.data_queue.task_done()
            except queue.Empty:
                time.sleep(0.01)
                continue
            except KeyboardInterrupt:
                self.stream_event.clear()
                break
        time.sleep(1)
        
        while self.data_queue.qsize() > 0:
            try:
                out, now = self.data_queue.get(timeout=1)
                out, now = self.process_output(out, format_out=format_out, data_type=data_type, timestamp=now)
                if out is not None:
                    buffer.append((out, now))
                self.data_queue.task_done()
            except queue.Empty:
                break
            except KeyboardInterrupt:
                break
        self.data_queue.join()
        return
    
    def _loop_stream(self,
        data:str|None = None, 
        sync_start:threading.Barrier|None = None,
        *,
        buffer: deque|None = None,
        format_out: str|None = None, 
        data_type: NamedTuple|None = None,
        split_stream: bool = True,
        callback: Callable[[str],Any]|None = None
    ):
        """
        Stream loop
        
        Args:
            data (str|None, optional): data to stream. Defaults to None.
            sync_start (threading.Barrier|None, optional): synchronization barrier. Defaults to None.
            buffer (deque|None, optional): buffer to store the streamed data. Defaults to None.
            format_out (str|None, optional): format for the data. Defaults to None.
            data_type (NamedTuple|None, optional): data type for the data. Defaults to None.
            split_stream (bool, optional): whether to split the stream and data processing threads. Defaults to True.
            callback (Callable[[str],Any]|None, optional): callback function to call with the streamed data. Defaults to None.
        """
        if not split_stream:
            if buffer is None:
                buffer = self.buffer
            assert isinstance(buffer, deque), "Ensure buffer is a deque"
        if isinstance(sync_start, threading.Barrier):
            sync_start.wait()
        if not callable(callback):
            def no_op_callback(_: str) -> None:
                return None

            callback = no_op_callback
        
        while self.stream_event.is_set():
            try:
                out = self.poll(data)
                now = datetime.now()
                if split_stream:
                    self.data_queue.put((out, now), block=False)
                else:
                    out, now = self.process_output(out, format_out=format_out, data_type=data_type, timestamp=now)
                    if out is not None:
                        buffer.append((out, now))
                        callback((out, now))
            except queue.Full:
                time.sleep(0.01)
                continue
            except KeyboardInterrupt:
                self.stream_event.clear()
                break
        return


class SerialDevice(BaseDevice):
    """
    SerialDevice provides an interface for handling serial devices
    
    ### Constructor:
        `port` (str|None, optional): serial port for the device. Defaults to None.
        `baudrate` (int, optional): baudrate for the device. Defaults to 9600.
        `timeout` (int, optional): timeout for the device. Defaults to 1.
        `init_timeout` (int, optional): timeout for initialization. Defaults to 2.
        `data_type` (NamedTuple, optional): data type for the device. Defaults to Data.
        `read_format` (str, optional): read format for the device. Defaults to READ_FORMAT.
        `write_format` (str, optional): write format for the device. Defaults to WRITE_FORMAT.
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
        `flags` (SimpleNamespace[str, bool]): flags for the device
        `is_connected` (bool): whether the device is connected
        `verbose` (bool): verbosity of class
        
    ### Methods:
        `clear`: clear the input and output buffers, and reset the data queue and buffer
        `connect`: connect to the device
        `disconnect`: disconnect from the device
        `check_device_connection`: check the connection to the device
        `check_device_buffer`: check the connection buffer
        `clear_device_buffer`: clear the device input and output buffers
        `read`: read data from the device
        `read_all`: read all data from the device
        `write`: write data to the device
        `poll`: poll the device (i.e. write and read data)
        `process_input`: process the input data
        `process_output`: process the output data
        `query`: query the device (i.e. write and read data)
        `start_stream`: start the stream
        `stop_stream`: stop the stream
        `stream`: toggle the stream
        `show_stream`: show the stream
    """
    
    def __init__(self,
        port: str|None = None, 
        baudrate: int = 9600, 
        timeout: int = 1, 
        *,
        init_timeout:int = 1, 
        data_type: NamedTuple = Data,
        read_format:str = READ_FORMAT,
        write_format:str = WRITE_FORMAT,
        simulation:bool = False, 
        verbose:bool = False,
        **kwargs
    ):
        """ 
        Initialize SerialDevice class
        
        Args:
            port (str|None, optional): serial port for the device. Defaults to None.
            baudrate (int, optional): baudrate for the device. Defaults to 9600.
            timeout (int, optional): timeout for the device. Defaults to 1.
            init_timeout (int, optional): timeout for initialization. Defaults to 2.
            data_type (NamedTuple, optional): data type for the device. Defaults to Data.
            read_format (str, optional): read format for the device. Defaults to READ_FORMAT.
            write_format (str, optional): write format for the device. Defaults to WRITE_FORMAT.
            simulation (bool, optional): whether to simulate the device. Defaults to False.
            verbose (bool, optional): verbosity of class. Defaults to False.
        """
        super().__init__(
            init_timeout=init_timeout, simulation=simulation, verbose=verbose, 
            data_type=data_type, read_format=read_format, write_format=write_format, **kwargs
        )
        self.connection: serial.Serial = serial.Serial()
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        return
    
    @property
    def serial(self) -> serial.Serial:
        """Serial object for the device"""
        return self.connection
    @serial.setter
    def serial(self, value:serial.Serial):
        assert isinstance(value, serial.Serial), "Ensure connection is a serial object"
        self.connection = value
        return
    
    @property
    def port(self) -> str:
        """Device serial port"""
        return self.connection_details.get('port', '')
    @port.setter
    def port(self, value:str):
        self.connection_details['port'] = value
        self.serial.port = value
        return
    
    @property
    def baudrate(self) -> int:
        """Device baudrate"""
        return self.connection_details.get('baudrate', 0)
    @baudrate.setter
    def baudrate(self, value:int):
        assert isinstance(value, int), "Ensure baudrate is an integer"
        assert value in serial.Serial.BAUDRATES, f"Ensure baudrate is one of the standard values: {serial.Serial.BAUDRATES}"
        self.connection_details['baudrate'] = value
        self.serial.baudrate = value
        return
    
    @property
    def timeout(self) -> int:
        """Device timeout"""
        return self.connection_details.get('timeout', 0)
    @timeout.setter
    def timeout(self, value:int):
        self.connection_details['timeout'] = value
        self.serial.timeout = value
        return
    
    def check_device_buffer(self) -> bool:
        """Check the connection buffer"""
        return self.serial.in_waiting
    
    def check_device_connection(self):
        """Check the connection to the device"""
        self.flags.connected = self.serial.is_open
        return self.flags.connected

    def clear_device_buffer(self):
        """Clear the device input and output buffers"""
        try:
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
        except serial.PortNotOpenError as e:
            self._logger.error(e)
        return

    def connect(self):
        """Connect to the device"""
        if self.is_connected:
            return
        try:
            self.serial.open()
        except serial.SerialException as e:
            self._logger.error(f"Failed to connect to {self.port} at {self.baudrate} baud")
            self._logger.debug(e)
        else:
            self._logger.info(f"Connected to {self.port} at {self.baudrate} baud")
            time.sleep(self.init_timeout)
        self.flags.connected = True
        return

    def disconnect(self):
        """Disconnect from the device"""
        if not self.is_connected:
            return
        self.stop_stream()
        try:
            self.serial.close()
        except serial.SerialException as e:
            self._logger.error(f"Failed to disconnect from {self.port}")
            self._logger.debug(e)
        else:
            self._logger.info(f"Disconnected from {self.port}")
        self.flags.connected = False
        return
    
    def read(self) -> str:
        """Read data from the device"""
        data = ''
        try:
            data = self.serial.readline().decode("utf-8", "replace").replace('\uFFFD', '')
            data = data.strip()
            self._logger.debug(f"[{self.port}] Received: {data!r}")
            self.serial.reset_output_buffer()
        except serial.SerialException:
            self._logger.debug(f"[{self.port}] Failed to receive data")
        except KeyboardInterrupt:
            self._logger.debug("Received keyboard interrupt")
            self.disconnect()
        return data
    
    def read_all(self) -> list[str]:
        """Read all data from the device"""
        delimiter = self.read_format.replace(self.read_format.rstrip(), '')
        data = ''
        try:
            while True:
                out = self.serial.read_all().decode("utf-8", "replace").replace('\uFFFD', '')
                data += out
                if not out:
                    break
        except serial.SerialException as e:
            self._logger.debug(f"[{self.port}] Failed to receive data")
            self._logger.debug(e)
        except KeyboardInterrupt:
            self._logger.debug("Received keyboard interrupt")
            self.disconnect()
        data = data.strip()
        self._logger.debug(f"[{self.port}] Received: {data!r}")
        return [d.strip() for d in data.split(delimiter) if len(d.strip())]
    
    def write(self, data:str) -> bool:
        """Write data to the device"""
        assert isinstance(data, str), "Ensure data is a string"
        try:
            self.serial.write(data.encode('utf-8'))
            self._logger.debug(f"[{self.port}] Sent: {data!r}")
        except serial.SerialException:
            self._logger.debug(f"[{self.port}] Failed to send: {data!r}")
            return False
        return True
