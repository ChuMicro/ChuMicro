# Guide

Slice 0 ships only the deploy-time config-merge core (`merge_configs`, `resolve_secrets`, `build_runtime_config`).  See [README](../README.md) for the public API surface; subsequent slices add command dispatch, three-zone YAML writer, onboarding flows, firmware URL derivation, and the import-graph resolver.
