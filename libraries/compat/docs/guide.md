# User Guide

## Overview

`chumicro-compat` provides lightweight reimplementations of CPython standard-library features that are missing or incomplete on MicroPython and CircuitPython.  It allows library authors to use familiar Python patterns across all three runtimes without depending on modules that don't exist on microcontrollers.

No modules are shipped yet.  Planned additions include `functools` polyfills.

## Platform notes

All future modules will target CPython, MicroPython, and CircuitPython using only basic Python features.
