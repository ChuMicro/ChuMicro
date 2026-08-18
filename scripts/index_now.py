"""Tell IndexNow-reading search engines that the docs changed.

IndexNow is a ping: publish a key file at the host root, then POST
the URLs that changed.  Bing, Yandex, and Seznam read the feed and
recrawl in minutes instead of waiting for their own schedule, which is
why it is worth the two dozen lines here.  Google does not
participate.

The key is public on purpose.  A crawler fetches
``https://<host>/<key>.txt`` and checks that it contains the key,
which proves the ping came from someone who can publish on the host.

The payload names no ``keyLocation``, which is what tells the endpoint
to look at the host root.  Pointing it at a subdirectory is legal in
the spec and was what this script did until 2026-08-18, but the
endpoint separately checks host ownership and answered every such ping
with ``403 UserForbiddedToAccessSite``.  The host root is where the
key has to be, so naming any other location only weakens the claim.

Called by ``docs_deploy_retry`` after a successful push.  A ping that
fails is reported and ignored: the docs are already live, and search
engines will find them on their own schedule.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from generate_landing_page import VERIFICATION_DIR, site_urls
from generate_site_root import HOST

#: IndexNow's shared endpoint.  Participating engines forward to each
#: other, so one POST reaches all of them.
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"

#: Where the key lives in the repository.  Its content is published at
#: the host root as ``<key>.txt``, and at the docs root as well so a
#: reader who finds one site finds the same key on the other.
KEY_FILE = VERIFICATION_DIR / "indexnow-key.txt"

#: The host the ping claims, taken from the root site so the two
#: cannot drift apart.
INDEXNOW_HOST = HOST.removeprefix("https://")


def read_key() -> str:
    """Return the IndexNow key, or an empty string when unset."""
    if not KEY_FILE.is_file():
        return ""
    return KEY_FILE.read_text().strip()


def key_filename(key: str) -> str:
    """Return the filename the key is published under at the host root."""
    return f"{key}.txt"


def submitted_urls() -> list[str]:
    """Return every URL the ping submits, host root first.

    The root page lists each package, so a release that adds or renames
    one changes that page as surely as it changes the documentation.
    """
    return [f"{HOST}/"] + site_urls()


def ping(timeout: float = 15.0) -> bool:
    """Submit every documentation URL to IndexNow.

    Returns ``True`` when the engines accepted the submission.  A
    missing key skips the ping and returns ``True``: a workspace that
    has not set one is not in an error state.

    A ``202`` means accepted, not validated.  The endpoint decides
    about host ownership later and answers a subsequent ping with
    ``403`` when it disagrees, so a green ping here is not on its own
    evidence that submissions are landing.
    """
    key = read_key()
    if not key:
        print("IndexNow: no key set, skipping ping.")
        return True

    urls = submitted_urls()
    payload = json.dumps({
        "host": INDEXNOW_HOST,
        "key": key,
        "urlList": urls,
    }).encode()
    request = urllib.request.Request(
        INDEXNOW_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            print(f"IndexNow: submitted {len(urls)} URLs (HTTP {response.status}).")
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
