# Decision 0114: MQTT client id defaults to a per-device hardware UID

Status: `accepted`
Date: `2026-07-18`
Summary: MQTTClient.from_config defaults client_id to a hardware-UID value (chumicro-<uid>), unique per device and stable across reboots, replacing the fixed "chumicro-mqtt" that collided on shared brokers.
Related: Decision [0064](0064-mqtt-three-tier-and-prefix-sugar.md) (the mqtt API surface), [0049](0049-three-runtime-trinity.md) (the CircuitPython / MicroPython / CPython runtime set).

## Context

`MQTTClient.from_config` defaulted `client_id` to the fixed string `"chumicro-mqtt"` when the config set none. MQTT 3.1.1 section 3.1.4 requires a broker to close an existing session when a second client connects with the same client id, so every device sharing a broker under this default evicts the others in a tight reconnect storm. A hardware E2E surfaced exactly this: three boards running the telemetry example against one public broker kicked each other continuously, which read at first like a MicroPython-specific client bug but was the shared id. The library's own `client_id` docstring already promised "unique per broker"; the fixed default broke that promise.

## Decision

`MQTTClient.from_config`, when the config carries no `mqtt.client_id`, defaults to a per-device id derived from the hardware UID via the module-level `chumicro_mqtt.default_client_id(prefix="chumicro")`.

- **Unique across devices, stable across reboots.** The id is `<prefix>-<uid-hex>`. Deriving from the hardware UID (not a random value) means a device keeps the same id across reboots, so an MQTT persistent session still resumes rather than orphaning on every restart.
- **Runtime-guarded UID source.** CircuitPython reads `microcontroller.cpu.uid`, MicroPython reads `machine.unique_id()`, and CPython (host or simulation) falls back to the host MAC via `uuid.getnode()`. Each source is import-guarded, so the helper never fails to construct; if none is available it returns the historical `<prefix>-mqtt`.
- **Config still wins.** An explicit `mqtt.client_id` (or the `client_id=` constructor argument on the core `MQTTClient`) overrides the default unchanged. Only the config-driven convenience constructor derives the id.
- **The hardware touch is isolated.** The core `MQTTClient` stays hardware-free (radio and socket are injected); only `default_client_id`, a single guarded convenience helper, reaches for the UID, and only when `from_config` needs a fallback.

## Rejected

- **A random per-boot id.** Unique, but changes every reboot, so a persistent (clean-session-false) subscription never resumes and the broker accumulates orphaned sessions. Hardware-UID is unique and stable.
- **Keeping the fixed default and only fixing the example.** The default is a shipped contract every `from_config` caller inherits; documenting around a broken default leaves the trap in place for the next multi-device user.
- **Deriving the UID inside the core protocol client.** Would couple the pure MQTT state machine to `microcontroller` / `machine`. Confining it to the `from_config` convenience path keeps the core injectable and testable without hardware.

## Consequences

- A device that relied on the literal `"chumicro-mqtt"` id (for a retained-session identity or a broker ACL) sees a one-time id change on upgrade; set `mqtt.client_id` explicitly to pin the old value.
- `default_client_id` is exported for callers who want the same id outside `from_config` (a will topic, a status channel).
- The helper is unit-tested for prefix, stability, and custom prefix; hardware-less runtimes (the unix-port test lanes) exercise the graceful `<prefix>-mqtt` fallback.
