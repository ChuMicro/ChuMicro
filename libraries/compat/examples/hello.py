"""Demonstrate abstract base classes with chumicro-compat.

Shows how ``ABC`` and ``@abstractmethod`` enforce the implementation
contract at instantiation time.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

from chumicro_compat.abc import ABC, abstractmethod


class Sensor(ABC):
    """A sensor that must provide a read() method."""

    @abstractmethod
    def read(self):
        """Return the current sensor reading."""


class TemperatureSensor(Sensor):
    """Concrete sensor that returns a fixed temperature."""

    def read(self):
        """Return a fake temperature reading."""
        return 22.5


# Concrete class works fine.
sensor = TemperatureSensor()
print(f"Temperature: {sensor.read()} °C")

# Abstract class raises TypeError.
try:
    Sensor()
except TypeError as exc:
    print(f"Expected error: {exc}")

