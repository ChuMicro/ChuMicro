"""Opt-in configuration loaders for :class:`~chumicro_deploy.Device`.

chumicro ships a loader for its own ``devices.yml`` shape in
:mod:`chumicro_deploy.config.chumicro` — importing it is opt-in so
third parties using their own config format pay no yaml-parser
import cost.  Register a custom loader via the
``chumicro_deploy.config_loaders`` Python entry point (Slice 1f.4).
"""
