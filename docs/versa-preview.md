# Authenticated Versa localhost preview

This scope uses direct User authority for two parties: the persistent Versa
Codex writer session `01a16a58-c741-7251-8e07-704ff4f04452` and Windows root
reviewer `/root`. The User explicitly selected this composition. The writer
read `AGENTS.md`, `policy/entry.md`, `policy/organization.md` and
`policy/execution.md` at ADRS commit
`897ef0c15e0ab8b85c181925708f367b14a6c7d8`. No preexisting job authority or
reviewer DQL anchor is claimed. The current GO covers source, local package
verification and dedicated branch/draft PR publication only.

`profile/versa-preview.nix` packages the single official Linux amd64
cloudflared 2026.10.3 release binary using its GitHub-provider SHA-256 digest.
It leaves nixpkgs and all existing profiles and services unchanged.

Build and verify without creating a result link:

```sh
nix build --no-link .#versa-preview .#versa-preview-cloudflared
nix build --no-link .#checks.x86_64-linux.versa-preview
```

The check invokes the packaged binary's version and actual tunnel help,
requiring `--allowed-mail`, and invokes the real app with invalid arguments.
Every invalid invocation must return usage with exit 64 before cloudflared
executes. It starts no tunnel and requires no mailbox or UI service.

After separate authorization for exposure and receipt of the exact allowed
mailbox, the intended interface is `nix run .#versa-preview -- PORT EXACT_EMAIL`.
Do not run it under the source-only GO. The observed candidate origin is
`http://127.0.0.1:18090`; a local HEAD 200 proves neither remote usability nor
authentication. Localhost belongs to Versa, not to a shared private network.

The app accepts exactly two arguments: a decimal port 1–65535 without leading
zeros and one conservative ASCII mailbox. It rejects wildcard/domain rules,
lists, whitespace, malformed domains and extra arguments. It constructs the
loopback URL and always passes `--allowed-mail`. An immutable empty YAML
configuration and an empty child environment with fixed HOME/XDG and CA bundle
prevent inherited cloudflared configuration, proxy or tunnel variables from
changing the route. It forwards no additional options. Initialization or
provisioning failure is an error; there is no unauthenticated fallback.

Upstream protected Quick Tunnels request Cloudflare Access OTP and install a
pre-origin authorizer; HTTPS alone is not authentication. The exact allowed
email is runtime input, not a committed credential. Quick Tunnels remain
temporary and have no uptime guarantee; this is not a production access service.
The selected upstream implementation is available at
https://github.com/cloudflare/cloudflared/blob/2026.10.3/cmd/cloudflared/tunnel/quick_tunnel.go.

No tunnel, target UI launch, daemon, account changes, keys, profile/PATH changes,
OS switch, merge, reboot or deletion are authorized here. Later live acceptance
must independently demonstrate anonymous and unauthorized-recipient refusal,
authorized mobile/browser UI use and required WebSocket behavior through the
same protected endpoint. Package/help checks alone do not establish that proof.
