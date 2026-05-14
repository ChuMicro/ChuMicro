"""In-repo fixture project for chumicro-workspace functional tests.

Exercises the workspace deploy chain end-to-end on a real board:

* The import-graph walker discovers ``chumicro_kvstore`` here, so the
  deploy must transitively stage the kvstore package + its deps
  (``chumicro_msgpack``, runtime-specific backend modules).
* ``run()`` writes to persistent storage and prints the resulting
  counter, so two deploys on the same board prove kvstore-backed
  state survives the boot.
* ``run()`` returns instead of looping forever, so the deploy's
  execute call completes within seconds and the test can read the
  full stdout in one shot.

Phase markers (``fixture: boot #N`` and ``fixture: done``) are
asserted by ``test_sensor_project_hardware.py`` — keep both strings
in sync if you rename them.
"""

from chumicro_kvstore import KVStore


def run() -> None:
    print("fixture: starting")
    store = KVStore(backend="auto")
    boot_count = store.get("boot_count", 0) + 1
    store["boot_count"] = boot_count
    store.commit()
    print(f"fixture: boot #{boot_count}")
    print("fixture: done")
