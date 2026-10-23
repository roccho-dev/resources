{ pkgs }:
let
  cloudflared = pkgs.stdenvNoCC.mkDerivation {
    pname = "versa-preview-cloudflared";
    version = "2026.10.3";
    src = pkgs.fetchurl {
      url = "https://github.com/cloudflare/cloudflared/releases/download/2026.10.3/cloudflared-linux-amd64";
      hash = "sha256:053b80b0a23031a038fdbf3c073f59f82b8f1f152aa67971d7383ffafc0dbab0";
    };
    dontUnpack = true;
    dontStrip = true;
    installPhase = ''
      install -Dm755 "$src" "$out/bin/cloudflared"
    '';
    meta.platforms = [ "x86_64-linux" ];
  };
  emptyConfig = pkgs.writeText "versa-preview-empty.yml" "{}\n";
  app = pkgs.writeShellApplication {
    name = "versa-preview";
    text = ''
      refuse() { echo 'usage: versa-preview PORT EXACT_EMAIL (one mailbox, no lists or wildcards)' >&2; exit 64; }
      [[ $# == 2 ]] || refuse
      port=$1 email=$2
      [[ $port =~ ^[1-9][0-9]{0,4}$ ]] || refuse
      (( port <= 65535 )) || refuse
      # Deliberately accept a conservative ASCII mailbox subset, never domain rules.
      mailbox='^[A-Za-z0-9]([A-Za-z0-9._%+-]*[A-Za-z0-9])?@[A-Za-z0-9.-]+$'
      [[ ''${#email} -le 254 && $email =~ $mailbox && $email != *..* ]] || refuse
      localpart=''${email%@*} domain=''${email#*@}
      [[ ''${#localpart} -le 64 && $domain == *.* ]] || refuse
      IFS=. read -r -a labels <<< "$domain"
      [[ $domain != *. ]] || refuse
      for label in "''${labels[@]}"; do
        [[ ''${#label} -le 63 && $label =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || refuse
      done
      # No inherited TUNNEL_*, proxy, certificate, HOME or XDG configuration.
      # Explicit config prevents cloudflared's normal config-file discovery.
      exec ${pkgs.coreutils}/bin/env -i HOME=/nonexistent XDG_CONFIG_HOME=/nonexistent \
        SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt \
        ${cloudflared}/bin/cloudflared tunnel --config ${emptyConfig} --no-autoupdate \
        --metrics 127.0.0.1:0 --url "http://127.0.0.1:$port" --allowed-mail "$email"
    '';
  };
in
{ inherit cloudflared app; }
