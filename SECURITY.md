# Security Policy

## Supported versions

Only the latest release gets security fixes. That covers the DazScriptServer
plugin (Daz Studio 4.x and the current Daz Studio 6 SDK build) and the
`dazpy` and `daz-ts` clients released with it. Upgrade before you report a
problem. It may already be fixed.

## Reporting a vulnerability

**Don't open a public issue for a security problem.**

Report it privately through GitHub:
**Security → Report a vulnerability** on
<https://github.com/bluemoonfoundry/daz-script-server/security/advisories/new>.

Please include:

- the plugin version (`GET /status` → `version`) and the Daz Studio version
- the server settings involved (host, auth, IP whitelist, rate limit)
- the steps to reproduce it, or a proof of concept
- what an attacker gains: the access they need before, and what they get after

You'll get a reply within 7 days. When a fix ships, the CHANGELOG entry will
credit you unless you'd rather stay anonymous.

## Scope

DazScriptServer exists to run arbitrary DazScript sent by an authenticated
client, and DazScript can read and write files the Daz Studio process can
reach. **What a valid token allows is by design, not a vulnerability.** See
[README → Security Features](README.md#-security-features) for the threat
model and the recommended settings.

In scope, for example:

- running a script, or reaching any authenticated route, without a valid
  token, or from an IP the whitelist should block
- recovering the token, or predicting a generated one
- getting past the body-size, rate, or concurrency limits in a way that
  crashes or hangs Daz Studio
- path traversal in archive extraction or artifact serving that reaches
  beyond what scripts can already read
- memory-safety bugs in request parsing

Out of scope:

- anything a valid token holder can do with DazScript
- running without auth, or binding to `0.0.0.0` with no IP whitelist, against
  the README's guidance
- no TLS. The server speaks plain HTTP; put a reverse proxy in front of it for
  remote access
