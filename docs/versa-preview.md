# Authenticated Versa localhost preview

Open a temporary, email-protected browser/mobile route to one UI listening on
Versa loopback. From this repository, supply its confirmed port and your exact
allowed mailbox:

```sh
nix run .#versa-preview -- PORT EXACT_EMAIL
```

Open the printed HTTPS URL and complete Cloudflare Access email OTP. Stop the
foreground command with Ctrl-C when finished. The minimal live proof is already
User-authorized; its missing inputs are the exact mailbox and confirmed UI
target. Do not substitute a guessed mailbox or expose an unrelated service.
Localhost belongs to Versa, not a shared private network.

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

The observed candidate origin is
`http://127.0.0.1:18090`; a local HEAD 200 proves neither remote usability nor
authentication, and the intended UI still needs confirmation.

The app accepts exactly two arguments: a decimal port 1–65535 without leading
zeros and one conservative ASCII mailbox. It rejects wildcard/domain rules,
lists, whitespace, malformed domains and extra arguments. It constructs the
loopback URL and always passes `--allowed-mail`. Metrics bind explicitly to
`127.0.0.1:0` (an ephemeral loopback port). An immutable empty YAML
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

Anonymous challenge proves only denial. Live acceptance must independently
demonstrate unauthorized-recipient refusal, authorized mobile/browser UI use
and required WebSocket behavior through the same protected endpoint.
Package/help checks and built-in Hello World do not establish that proof.
