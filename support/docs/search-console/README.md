# Search Console verification

Google Search Console proves you own a site before it shows you what
people search for to reach it.  Both files here are read at docs-deploy
time and published to the root of the documentation site, so a
verification survives every redeploy instead of being overwritten by
the next one.

## HTML tag (the one to use)

Add `https://chumicro.github.io/ChuMicro/` in Search Console as a **URL
prefix** property, choose the **HTML tag** method, and copy the value
out of `content="..."`.  Write that value, and nothing else, to
`meta-tag.txt` in this directory:

```
abc123DEFghi456JKLmno789
```

The landing page generator turns it into
`<meta name="google-site-verification" content="...">` in the head of
`index.html`.  Deploy the docs, then press Verify.

Keep the file after verifying.  Google rechecks it, and removing it
un-verifies the property.

## HTML file (the alternative)

If you would rather use the **HTML file** method, drop the
`google<hash>.html` file Search Console hands you into this directory.
Every `.html` file here is published verbatim at the root of the docs
site, which is where Search Console looks for it.

## Domain properties

A domain property is not available for this site.  `github.io` sits on
the public suffix list and the DNS belongs to GitHub, so the URL-prefix
property above is the one to verify.
