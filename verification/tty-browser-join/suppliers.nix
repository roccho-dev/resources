# C-side expectations, NOT A/B acceptance or product/version authority.
# Related: https://github.com/roccho-dev/adrs/issues/630#issuecomment-6139949993
# Fill only after an owner-provided export and its exact source are confirmed.
# Each value: { package = <existing Nix derivation>; rev = <source commit>;
#               narHash = <source NAR hash>; }
# No mutable branch, local ZIP/path, recreated package recipe, or test substitute.
{
  A = null; # ops PR534: bin/cdp-tty, attach-only, TTY/Kitty, no input retry.
  B = null; # Meltype PR3: bin/meltype-tty, existing Core/Mozc, --raw-text -- child.
  terminal = null; # Existing bcon Producer export; C does not copy its recipe.
}
