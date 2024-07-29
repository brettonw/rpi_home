from __future__ import annotations

import json
import subprocess
import os
import time
import socket
import importlib
import logging
from typing import Any

from .version import RPI_HOME_VERSION
from .const import RPI_HOME_DIR, NAME, VERSION, SENSORS, CONTROLS, TIMESTAMP, HOST, IP_ADDRESS, OPERATING_SYSTEM, MODULE_NAME, CLASS_NAME
from .utils import get_lines_from_proc, load_json_file, put_if_not_none
from .rpi_sensor import RpiSensor

_LOGGER = logging.getLogger(__name__)


def _get_ip_address() -> str:
    for line in get_lines_from_proc(["ip", "-o", "-4", "addr", "list"]):
        if 'eth0' in line or 'wlan0' in line:
            return line.split()[3].split("/")[0]
    # if we didn't get anything else...
    return socket.gethostbyname(socket.gethostname())


def _get_os_description() -> str:
    for line in get_lines_from_proc(["lsb_release", "-a"]):
        if "Description" in line:
            return line.split(':')[1].strip()
    # if we didn't get anything else
    return "unknown"


class RpiSensorDevice:
    def __init__(self):
        config_file = os.path.join(RPI_HOME_DIR, "config.json")
        if os.path.isfile(config_file):
            with open(config_file, 'r') as config_file:
                self.config = json.load(config_file)

    @property
    def config(self) -> dict[str, Any]:
        return self.config

    @staticmethod
    def import_class_from_module(module_name: str, class_name: str) -> RpiSensor | None:
        # condition the module name to start with "rpi_home_"
        if not module_name.startswith("rpi_home_"):
            module_name = "rpi_home_" + module_name

        # try to load the module
        try:
            imported_module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            _LOGGER.error(f"module ({module_name}) not found.")
            return None

        # try to get the requested class
        try:
            imported_class = getattr(imported_module, class_name)
        except AttributeError:
            _LOGGER.error(f"class ({class_name}) not found in module '{module_name}'.")
            return None

        # ensure that the found attribute is a subclass of RpiSensor
        if not issubclass(imported_class, RpiSensor):
            print(f"class ({class_name}) in module ({module_name}) is not an RpiSensor subclass.")
            return None

        return imported_class

    def report(self) -> dict:
        output_sensors = []
        output = {
            VERSION: RPI_HOME_VERSION,
            TIMESTAMP: int(time.time() * 1000),
            HOST: {
                NAME: socket.gethostname(),
                IP_ADDRESS: _get_ip_address(),
                OPERATING_SYSTEM: _get_os_description()
            },
            SENSORS: output_sensors
        }

        # load the control states and include them (if any)
        put_if_not_none(output, CONTROLS, load_json_file(os.path.join(RPI_HOME_DIR, "controls.json")))

        # loop through the config to read each sensor
        sensors = self.config[SENSORS]
        for sensor in sensors:
            # sensor has a name, a pip module dependency, and a python class to use as a driver - which should be a module installed using pip
            # XXX do I even need the name? what if I have a bunch of drivers that report the same name, like temperature?
            _LOGGER.debug(f"reading sensor ({sensor[NAME]})")
            cls = self.import_class_from_module(sensor[MODULE_NAME], sensor.get(CLASS_NAME, "Driver"))
            if cls is not None:
                sensor_outputs = cls.report()
                if sensor_outputs is not None:
                    output_sensors.extend(sensor_outputs)

        return output
