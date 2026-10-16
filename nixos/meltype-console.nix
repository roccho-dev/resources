# Japanese input on VersaPro's physical console: fork Meltype's Direct TTY (meltype-tty) inside bcon.
# Use: log in as `meltype` on a getty VT; the login starts `bcon --backend=seatd` with `meltype-tty --raw-text`
# as bcon's shell. If bcon exits or fails, the login continues in the normal shell.
# No system service, no autologin, no password or other secret (the User sets it on the host).
{ bcon, meltype-src, meltype-linux }:
{ pkgs, ... }:
let
  # sanohiro/bcon (MIT). Source and Cargo.lock come from the locked flake input. Run rootless, bcon
  # starts the user's $SHELL (it uses /bin/login only as root), so no login path patch is needed.
  bconPackage = pkgs.rustPlatform.buildRustPackage {
    pname = "bcon";
    version = "1.5.1";
    src = bcon;
    cargoLock.lockFile = "${bcon}/Cargo.lock";
    nativeBuildInputs = [ pkgs.pkg-config pkgs.makeWrapper ];
    buildInputs = with pkgs; [ libdrm libgbm libxkbcommon libinput systemd fontconfig freetype seatd ];
    postFixup = ''
      wrapProgram "$out/bin/bcon" --prefix LD_LIBRARY_PATH : "${pkgs.lib.makeLibraryPath [ pkgs.libglvnd pkgs.seatd ]}"
    '';
    meta = { license = pkgs.lib.licenses.mit; mainProgram = "bcon"; platforms = pkgs.lib.platforms.linux; };
  };
  # The release's Linux zip is a plain file input: it has a non-ASCII member name that the flake
  # tarball fetcher cannot unpack, so unzip it here.
  meltypeLinux = pkgs.runCommand "meltype-linux-1.2.1.3" { nativeBuildInputs = [ pkgs.unzip ]; } ''
    unzip -q ${meltype-linux}
    mv Meltype-linux $out
  '';
  # Split B's own package expression, fed with that unpacked zip.
  meltypeTty = import "${meltype-src}/linux/tty/package.nix" {
    inherit pkgs;
    packagePath = "${meltypeLinux}";
  };
  # bcon (rootless) runs `$SHELL` as its child with no arguments and has no shell setting, so bcon is
  # started with SHELL pointing here. meltype-tty then wraps the normal shell (its default child is $SHELL).
  meltypeShell = pkgs.writeShellScript "meltype-shell" ''
    export SHELL=${pkgs.bashInteractive}/bin/bash
    exec ${meltypeTty}/bin/meltype-tty --raw-text
  '';
in
{
  # bcon draws through GBM; mesa's GBM backend lives under /run/opengl-driver, which this provides.
  hardware.graphics.enable = true;
  services.seatd.enable = true;
  users.users.meltype = {
    isNormalUser = true;
    description = "Meltype console";
    extraGroups = [ "seat" "video" "input" ];
  };
  # Direct TTY: bcon's own IME stays off; meltype-tty does the conversion.
  environment.etc."bcon/config.toml".text = ''
    [terminal]
    ime = false
  '';
  fonts.packages = [ pkgs.noto-fonts-cjk-sans ];
  environment.systemPackages = [ bconPackage meltypeTty ];
  # Default for `meltype` on a physical console VT only: not over SSH, not for other users, not again
  # inside bcon (bcon sets TERM_PROGRAM=bcon; MELTYPE_CONSOLE marks this session). bcon is not exec'd,
  # so when it exits or fails the login continues in the normal shell.
  environment.loginShellInit = ''
    if [ "$(id -un)" = meltype ] && [ -z "''${SSH_CONNECTION-}" ] && [ -z "''${MELTYPE_CONSOLE-}" ] && [ "''${TERM_PROGRAM-}" != bcon ]; then
      case "$(tty 2>/dev/null)" in
        /dev/tty[0-9]*)
          export MELTYPE_CONSOLE=1
          SHELL=${meltypeShell} ${bconPackage}/bin/bcon --backend=seatd ||
            echo "meltype-console: bcon exited with status $?; continuing in the normal shell." >&2
          ;;
      esac
    fi
  '';
}
