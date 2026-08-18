# Site verification and crawler pings

Search engines want proof you own a site before they report what
people searched to reach it, and they want to be told when pages
change.  Everything here is read at docs-deploy time and published to
two places: the documentation site at
`https://chumicro.github.io/ChuMicro/`, and the host root at
`https://chumicro.github.io/`.  Both are rebuilt from this directory on
every deploy, so a token survives the branch rewrite the deploy
performs.

## Google Search Console

`google-meta-tag.txt` holds the token from Search Console's **HTML
tag** method, on one line and nothing else:

```
abc123DEFghi456JKLmno789
```

Both landing-page generators write it into the head of their
`index.html` as `<meta name="google-site-verification" content="...">`.
Add `https://chumicro.github.io/` as a **URL prefix** property, paste
the token here, deploy the docs, then press Verify.  The same token
verifies `https://chumicro.github.io/ChuMicro/` as a second property,
which is worth having: Search Console reports queries per property, and
the project property is the one that shows how the library pages are
found.

A domain property is not available: `github.io` sits on the public
suffix list and its DNS belongs to GitHub.

## Bing Webmaster Tools

`bing-meta-tag.txt` works the same way and becomes
`<meta name="msvalidate.01" content="...">`.  Bing matters more than
its search share suggests, because Copilot and ChatGPT's search path
read Bing's index.

Verify `https://chumicro.github.io/` here as well as the project path.
The root property is what makes IndexNow work, as the next section
explains.

## Verification files

Any `*.html` or `*.xml` file in this directory publishes verbatim at
both site roots.  That covers Search Console's `google<hash>.html`
method and Bing's `BingSiteAuth.xml`, for anyone who prefers a file to
a tag.  Publishing at the host root is what lets those files verify the
root property; the copies under `/ChuMicro/` verify the project one.

## IndexNow

`indexnow-key.txt` holds the key that authorizes instant-indexing
pings.  The key publishes at both site roots as `<key>.txt`, which is
how IndexNow checks that whoever pings can publish on the site, and a
successful docs deploy submits every documentation URL to
`api.indexnow.org`.  Bing, Yandex, and Seznam read that feed; Google
does not.

The key is not a secret.  It is public by design: crawlers fetch it
from the site to confirm the ping came from someone who can publish
there.  Replace it by writing a new hex string here; the next deploy
publishes the new file and pings with it.

### Why the key has to sit at the host root

A key published only under `/ChuMicro/` drew
`403 UserForbiddedToAccessSite` on 2026-08-17, and three separate keys
behaved the same way.  The spec allows a key file outside the host root
when the ping names it in `keyLocation`, which the ping does, so the
key location was a red herring.  What the endpoint checks is whether
the submitter owns the **host**, and `chumicro.github.io` carries every
GitHub Pages project site in the organization.

Two results made this readable.  A brand new key returned `202` while
its file was still a 404, so a `202` means accepted rather than
validated.  The same key five minutes later, with the file answering
`200`, returned the `403`.  The key was never the variable.

The fix is owning the root: the `ChuMicro/chumicro.github.io`
repository publishes at `https://chumicro.github.io/`, the deploy
writes `<key>.txt` there, and Bing's root property covers every path on
the host.  See the next section.

The ping names no `keyLocation` now that the key answers at the root,
because an absent one is what tells the endpoint to look there.  Naming
a subdirectory is what the script did until 2026-08-18, and it only
ever weakened the claim.

A refused ping warns and leaves the deploy green.

Rotating the key is one edit here.  The next deploy publishes the new
file and removes the old one at both roots, so a key that is no longer
live cannot keep authorizing pings.

## The host-root site

`scripts/generate_site_root.py` builds the page at
`https://chumicro.github.io/` and the files that describe the whole
host, and the docs-deploy workflow pushes them to the
`ChuMicro/chumicro.github.io` repository.  Three things live there
because they only count at a host root:

- `robots.txt`.  Crawlers read it at the root and nowhere else, so a
  project path cannot advertise a sitemap this way.  The generated file
  names every sitemap on the host.
- The ownership tokens, which verify the root property and with it
  every path below.
- The IndexNow key.

Publishing needs a deploy key.  Generate a keypair, add the public half
to the `chumicro.github.io` repository as a deploy key with write
access, and add the private half to `ChuMicro/ChuMicro` as the
`SITE_ROOT_DEPLOY_KEY` secret.  Without it the publish job warns and
the documentation deploy still succeeds.

One rule for that repository: no folder in it may be named after a
project repository.  GitHub serves `ChuMicro/AiFi` at
`https://chumicro.github.io/AiFi/`, so a folder of that name would
claim an address that already belongs to a site.
