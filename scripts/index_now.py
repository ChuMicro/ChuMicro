"""Tell IndexNow-reading search engines that the docs changed.

IndexNow is a ping: publish a key file at the site root, then POST the
URLs that changed along with that key's location.  Bing, Yandex, and
Seznam read the feed and recrawl in minutes instead of waiting for
their own schedule, which is why it is worth the two dozen lines here.
Google does not participate.

The key is public on purpose.  A crawler fetches
``<site>/<key>.txt`` and checks that it contains the key, which proves
the ping came from someone who can publish on the site.

Called by ``docs_deploy_retry`` after a successful push.  A ping that
fails is reported and ignored: the docs are already live, and search
engines will find them on their own schedule.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from generate_landing_page import SITE_ROOT, VERIFICATION_DIR, site_urls

#: IndexNow's shared endpoint.  Participating engines forward to each
#: other, so one POST reaches all of them.
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"

#: Where the key lives in the repository.  Its content is published at
#: the docs root as ``<key>.txt``.
KEY_FILE = VERIFICATION_DIR / "indexnow-key.txt"


def read_key() -> str:
    """Return the IndexNow key, or an empty string when unset."""
    if not KEY_FILE.is_file():
        return ""
    return KEY_FILE.read_text().strip()


def key_filename(key: str) -> str:
    """Return the filename the key is published under at the site root."""
    return f"{key}.txt"


def ping(timeout: float = 15.0) -> bool:
    """Submit every documentation URL to IndexNow.

    Returns ``True`` when the engines accepted the submission.  A
    missing key skips the ping and returns ``True``: a workspace that
    has not set one is not in an error state.
    """
    key = read_key()
    if not key:
        print("IndexNow: no key set, skipping ping.")
        return True

    payload = json.dumps({
        "host": "chumicro.github.io",
        "key": key,
        "keyLocation": f"{SITE_ROOT}/{key_filename(key)}",
        "urlList": site_urls(),
    }).encode()
    request = urllib.request.Request(
        INDEXNOW_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            print(f"IndexNow: submitted {len(site_urls())} URLs (HTTP {response.status}).")
            return True
    except urllib.error.HTTPError as error:
        print(f"WARNING: IndexNow rejected the ping: HTTP {error.code} {error.reason}")
        # HTTPError holds the response body open.  Closing it keeps the
        # interpreter from warning about the leak at collection time.
        error.close()
    except OSError as error:
        print(f"WARNING: IndexNow ping failed: {error}")
    return False


if __name__ == "__main__":
    raise SystemExit(0 if ping() else 0)
