# Site verification and crawler pings

Search engines want proof you own a site before they report what
people searched to reach it, and they want to be told when pages
change.  Everything here is read at docs-deploy time and published to
the root of the documentation site, so it survives the branch rewrite
every deploy performs.

## Google Search Console

`google-meta-tag.txt` holds the token from Search Console's **HTML
tag** method, on one line and nothing else:

```
abc123DEFghi456JKLmno789
```

The landing page generator writes it into the head of `index.html` as
`<meta name="google-site-verification" content="...">`.  Add
`https://chumicro.github.io/ChuMicro/` as a **URL prefix** property,
paste the token here, deploy the docs, then press Verify.

A domain property is not available: `github.io` sits on the public
suffix list and its DNS belongs to GitHub.

## Bing Webmaster Tools

`bing-meta-tag.txt` works the same way and becomes
`<meta name="msvalidate.01" content="...">`.  Bing matters more than
its search share suggests, because Copilot and ChatGPT's search path
read Bing's index.

## Verification files

Any `*.html` or `*.xml` file in this directory publishes verbatim at
the docs-site root.  That covers Search Console's `google<hash>.html`
method and Bing's `BingSiteAuth.xml`, for anyone who prefers a file to
a tag.

## IndexNow

`indexnow-key.txt` holds the key that authorizes instant-indexing
pings.  The key is published at the docs root as `<key>.txt`, which is
how IndexNow checks that whoever pings owns the site, and a successful
docs deploy submits every documentation URL to
`api.indexnow.org`.  Bing, Yandex, and Seznam read that feed; Google
does not.

The key is not a secret.  It is public by design: crawlers fetch it
from the site to confirm the ping came from someone who can publish
there.  Replace it by writing a new hex string here; the next deploy
publishes the new file and pings with it.
