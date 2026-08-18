# Decision 0121: Documentation publishes under chumicro.com

Status: `accepted`
Date: `2026-08-18`
Summary: the documentation moves to the registered domain `chumicro.com`, GitHub redirects every `chumicro.github.io` address, project paths are unchanged, and `site_host.py` names the host once.
Related: 0013, 0019

## Context

The documentation published under `chumicro.github.io`, an address GitHub grants and every Pages site in the organization shares.  That sharing had costs that only showed up once search engines got involved.

`github.io` sits on the public suffix list, so no one can hold a Search Console domain property for it and its DNS belongs to GitHub.  IndexNow refused every submission with `403 UserForbiddedToAccessSite` for two days because the endpoint checks host ownership separately from the key, and nobody owns a host they share.  Claiming the `chumicro.github.io` repository (2026-08-18) fixed the immediate refusal by putting `robots.txt`, the ownership tokens, and the key at the host root, but the host itself stayed something Bing granted rather than something the project held.

The project already owned `chumicro.com`, `chumicro.net`, and `chumicro.org`, registered through 2031 and forwarding to the GitHub organization page.  Google had not yet fetched the sitemap, so nothing had accumulated ranking that a move would disturb.  That made the moment unusually cheap: the same move in three months costs real position.

## Decision

- `chumicro.com` is the canonical host.  The hub publishes at `https://chumicro.com/` and the documentation at `https://chumicro.com/ChuMicro/`, with per-package addresses such as `https://chumicro.com/ChuMicro/mqtt/stable/`.
- Paths are unchanged.  Only the host moved, so every address below `/ChuMicro/` keeps the shape Decision 0013 gave it, and a future project takes a sibling path rather than a second host.
- `scripts/site_host.py` names the host once.  The landing page, the host-root site, both sitemaps, the structured data, and the IndexNow ping all read it, and its `CUSTOM_DOMAIN` constant is what makes the host-root site publish the `CNAME` file GitHub reads.
- `chumicro.net` and `chumicro.org` redirect to `chumicro.com`.  They are never verified, never indexed, and never serve content: three hosts answering with the same pages would split the site's authority and let a search engine pick a winner arbitrarily.
- The `chumicro.github.io` addresses stay live as redirects.  GitHub issues them automatically for a custom-domained organization site, so links published before the move keep working without a redirect table anyone has to maintain.

Rejected: staying on `chumicro.github.io`, which costs nothing today but keeps the public-suffix limits permanently, on a host the project cannot verify as its own.

Rejected: giving each project its own domain, or its own `<name>.github.io` organization.  Authority accrues per host, so splitting projects across hosts means starting from nothing each time.

## Consequences

- The `CNAME` file has to be generated, not committed by hand.  A publish rebuilds the site repository's whole tree, so a `CNAME` written there by GitHub's web interface would be deleted by the next deploy and take the domain down with it.
- Setting `CUSTOM_DOMAIN` is only safe once the domain's DNS already resolves to GitHub.  The redirect off `github.io` starts the moment GitHub accepts the domain, so a `CNAME` that lands first points every visitor at a name that does not answer.
- Search Console and Bing both need properties for the new host, and Bing needs one before IndexNow accepts pings for it.  The DNS is now the project's own, so Search Console can take a domain property covering every subdomain and both schemes at once.
- The PyPI `Documentation` links move with the next release.  Until then they point at addresses that redirect, which costs a hop and nothing else.
