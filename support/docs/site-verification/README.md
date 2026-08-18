# Site verification and crawler pings

Search engines want proof you own a site before they report what
people searched to reach it, and they want to be told when pages
change.  Everything here is read at docs-deploy time and published to
two places: the documentation site at `https://chumicro.com/ChuMicro/`,
and the host root at `https://chumicro.com/`.  Both are rebuilt from
this directory on every deploy, so a token survives the branch rewrite
the deploy performs.

The site moved from `chumicro.github.io` to `chumicro.com` on
2026-08-18.  GitHub redirects every old address to the matching new
one, so nothing published before the move broke, but the properties
below all describe the new host.

## Google Search Console

`google-meta-tag.txt` holds the token from Search Console's **HTML
tag** method, on one line and nothing else:

```
abc123DEFghi456JKLmno789
```

Both landing-page generators write it into the head of their
`index.html` as `<meta name="google-site-verification" content="...">`.
Add `https://chumicro.com/` as a **URL prefix** property, paste
the token here, deploy the docs, then press Verify.  The same token
verifies `https://chumicro.com/ChuMicro/` as a second property,
which is worth having: Search Console reports queries per property, and
the project property is the one that shows how the library pages are
found.

Prefer a **domain property** for `chumicro.com` where you can.  It
covers every subdomain and both schemes at once, and it verifies with
a TXT record in the domain's DNS.  This became possible only with the
move off `chumicro.github.io`, which sits on the public suffix list
and whose DNS belongs to GitHub.

## Bing Webmaster Tools

`bing-meta-tag.txt` works the same way and becomes
`<meta name="msvalidate.01" content="...">`.  Bing matters more than
its search share suggests, because Copilot and ChatGPT's search path
read Bing's index.

Verify `https://chumicro.com/` here as well as the project path.
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
behaved the same way.  This was on the old `chumicro.github.io` host,
which every GitHub Pages site in the organization shared.  The spec allows a key file outside the host root
when the ping names it in `keyLocation`, which the ping does, so the
key location was a red herring.  What the endpoint checks is whether
the submitter owns the **host**, and `chumicro.github.io` carried every
GitHub Pages project site in the organization.

Two results made this readable.  A brand new key returned `202` while
its file was still a 404, so a `202` means accepted rather than
validated.  The same key five minutes later, with the file answering
`200`, returned the `403`.  The key was never the variable.

The fix is owning the root: the `ChuMicro/chumicro.github.io`
repository publishes at `https://chumicro.com/`, the deploy writes
`<key>.txt` there, and Bing's root property covers every path on the
host.  See the next section.

Moving to `chumicro.com` settles the ownership question for good.  The
host is a domain the project registered rather than a name shared with
every other Pages site, so verifying it in Bing is verifying something
that is genuinely yours.

The ping names no `keyLocation` now that the key answers at the root,
because an absent one is what tells the endpoint to look there.  Naming
a subdirectory is what the script did until 2026-08-18, and it only
ever weakened the claim.

Confirmed working on 2026-08-18: with the key at the host root, no
`keyLocation` in the payload, and the root property verified in Bing,
the endpoint answers `200` rather than `202` or `403`.  A `200` is the
one that means the submission was taken.  That was on the old host;
`chumicro.com` needs its own Bing property before pings for it are
accepted.

A refused ping warns and leaves the deploy green.

Rotating the key is one edit here.  The next deploy publishes the new
file and removes the old one at both roots, so a key that is no longer
live cannot keep authorizing pings.

## The host-root site

`scripts/generate_site_root.py` builds the page at
`https://chumicro.com/` and the files that describe the whole
host, and the docs-deploy workflow pushes them to the
`ChuMicro/chumicro.github.io` repository.  Three things live there
because they only count at a host root:

- `robots.txt`.  Crawlers read it at the root and nowhere else, so a
  project path cannot advertise a sitemap this way.
- `sitemap.xml`, which is a sitemap **index** rather than a list of
  URLs.  A sitemap at the host root is the only one whose scope is the
  whole host, so submitting `https://chumicro.com/sitemap.xml`
  once to a search engine covers every project below it.  Adding a
  project adds a line to the index rather than a submission someone has
  to remember to make.
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
`https://chumicro.com/AiFi/`, so a folder of that name would claim an
address that already belongs to a site.

## The custom domain

`scripts/site_host.py` names the host once and every generated URL
reads it, so moving hosts is an edit there plus a sweep of the static
files that spell the address out in prose.

`CUSTOM_DOMAIN` also makes the host-root site publish a `CNAME` file,
which is the file GitHub reads to learn the domain.  Generating it
matters because a publish rebuilds the whole tree: a `CNAME` added by
hand, or written into the repository by GitHub when someone sets the
domain in the web interface, would be deleted by the next deploy and
take the domain down.

Set `CUSTOM_DOMAIN` only after the domain's DNS already resolves to
GitHub's servers.  GitHub begins redirecting the `github.io` address
the moment it accepts the domain, so a `CNAME` that lands first sends
every visitor to a name that does not answer yet.

The DNS records the domain needs are four `A` records on the apex
pointing at `185.199.108.153` through `185.199.111.153`, the four
matching `AAAA` records on `2606:50c0:8000::153` through
`2606:50c0:8003::153`, and a `CNAME` on `www` pointing at
`chumicro.github.io`.  GitHub redirects `www` to the apex once the
apex is the configured domain.
