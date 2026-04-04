# User Guide

## Overview

`chumicro-compat` provides lightweight reimplementations of CPython standard-library features that are missing or incomplete on MicroPython and CircuitPython.  It allows library authors to use familiar Python patterns — like abstract base classes — across all three runtimes without depending on modules that don't exist on microcontrollers.

Currently provides `chumicro_compat.abc` (abstract base classes).  Future additions may include `functools` polyfills.

## Getting started

```python
from chumicro_compat.abc import ABC, abstractmethod


class Sensor(ABC):

    @abstractmethod
    def read(self):
        """Subclasses must implement this."""


class TemperatureSensor(Sensor):

    def read(self):
        return 22.5


sensor = TemperatureSensor()  # OK
Sensor()                      # TypeError
```

## Abstract base classes

### Defining abstract classes

Decorate methods with `@abstractmethod` and inherit from `ABC`:

```python
from chumicro_compat.abc import ABC, abstractmethod


class Transport(ABC):

    @abstractmethod
    def send(self, data):
        """Send data over the transport."""

    @abstractmethod
    def receive(self):
        """Receive data from the transport."""
```

Any class that leaves abstract methods unimplemented will raise `TypeError` on instantiation.  The error message lists the missing methods.

### Multi-level inheritance

Abstract methods can be spread across multiple levels.  Each level can add new abstract methods or implement existing ones:

```python
class Base(ABC):

    @abstractmethod
    def connect(self):
        """Must implement."""


class SecureBase(Base):

    @abstractmethod
    def handshake(self):
        """Must implement."""


class SecureClient(SecureBase):

    def connect(self):
        return True

    def handshake(self):
        return True


SecureClient()   # OK — both methods implemented
SecureBase()     # TypeError — connect and handshake missing
```

### Constructor arguments

Concrete classes with `__init__` arguments work normally:

```python
class Sensor(ABC):

    @abstractmethod
    def read(self):
        """Must implement."""


class TempSensor(Sensor):

    def __init__(self, pin):
        self._pin = pin

    def read(self):
        return self._pin.value


sensor = TempSensor(pin=board.A0)
```

## Platform notes

Requires `__init_subclass__` support, available on MicroPython ≥1.19.1 and CircuitPython ≥8.x.  Works identically on CPython.  No metaclasses, no `abc` standard-library dependency.

## Memory notes

Abstract method collection (`dir()` + `getattr()`) runs once per class definition in `__init_subclass__`, not per instance.  The per-class `__abstractmethods__` set is small (typically 1–3 entries).  The `__new__` check at instantiation is a single `getattr` + truthiness test.
