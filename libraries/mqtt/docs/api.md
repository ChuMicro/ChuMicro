# API Reference

`MQTTClient` is the class a program builds first, usually through `MQTTClient.from_config()`.  Its entry under `chumicro_mqtt.client` lists every method and callback.  `from chumicro_mqtt import MQTTClient` imports the same class.  The `chumicro_mqtt` section holds the exception types and `topic_matches()`.

## `chumicro_mqtt`

The exception types the client raises or stores in `last_error`, and `topic_matches()`, which tests a topic against a subscription filter.

::: chumicro_mqtt

## `chumicro_mqtt.client`

`MQTTClient`, the `ProtocolState` names its `state` moves through, the `InboundPublish` record `next_message()` returns, the `WhenOversized` policy names, and `default_client_id()`.

::: chumicro_mqtt.client
    options:
      members:
        - MQTTClient
        - ProtocolState
        - InboundPublish
        - WhenOversized
        - default_client_id

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt) · \
[PyPI](https://pypi.org/project/chumicro-mqtt/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
