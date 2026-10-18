# Japanese input on VersaPro's physical console: fork Meltype's Direct TTY (meltype-tty) inside bcon.
# Use: log in as `meltype` on a getty VT; the login becomes bcon (seatd backend) with `meltype-tty --raw-text`
# as bcon's shell. No shell stays under bcon: when bcon exits or fails, the session ends and getty returns.
# No system service, no autologin, no password or other secret (the User sets it on the host).
# The terminal font is the shared selection in profile/fonts.nix, built with this host's nixpkgs.
{ bcon, meltype-src, meltype-linux, ... }@inputs:
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
  # Fonts shared with the Windows host: profile/fonts.nix (the files and fonts.json whose families its
  # build checks). The terminal role's family and its Regular file come from fonts.json.
  commonFonts = (import ../profile/fonts.nix { inherit pkgs; }).commonFonts;
  terminalFonts = builtins.filter (entry: entry.role == "terminal")
    (builtins.fromJSON (builtins.readFile "${commonFonts}/fonts.json"));
  terminalFamily = (builtins.head terminalFonts).family;
  terminalRegular = builtins.filter (entry: entry.fullName == "${terminalFamily} Regular") terminalFonts;
  terminalFont = assert builtins.length terminalRegular == 1;
    "${commonFonts}/share/fonts/truetype/${(builtins.head terminalRegular).file}";
  # bcon (rootless) runs `$SHELL` as its child with no arguments and has no shell setting, so bcon is
  # started with SHELL pointing here. meltype-tty then wraps the normal shell (its default child is $SHELL).
  # The trailing --font overrides package.nix's (argparse keeps the last one) for the candidate images.
  meltypeShell = pkgs.writeShellScript "meltype-shell" ''
    export SHELL=${pkgs.bashInteractive}/bin/bash
    exec ${meltypeTty}/bin/meltype-tty --raw-text --preview --font ${terminalFont}
  '';
  # meltype's login shell. bcon itself cannot be it: login sets SHELL to the login shell, and bcon would
  # start itself as its child. So this sets SHELL (and the backend, BCON_BACKEND) and execs bcon: the
  # process chain is getty → login → bcon → meltype-tty → bash, with no shell layer left in between.
  # set-environment gives bcon and meltype-tty the NixOS environment a login shell would have had.
  meltypeLogin = (pkgs.writeShellScriptBin "meltype-login" ''
    # login(1) starts the login shell with no arguments; on a console VT that session becomes bcon.
    if [ "$#" -eq 0 ]; then
      case "$(${pkgs.coreutils}/bin/tty 2>/dev/null)" in
        /dev/tty[0-9]*)
          . /etc/set-environment
          export SHELL=${meltypeShell} BCON_BACKEND=seatd
          exec ${bconPackage}/bin/bcon
          ;;
      esac
    fi
    # Anything else (`su meltype -c …`, sshd's `-c` for ssh/scp, no console VT) gets the normal bash.
    export SHELL=${pkgs.bashInteractive}/bin/bash
    if [ "$#" -eq 0 ]; then exec "$SHELL" --login; fi
    exec "$SHELL" "$@"
  '').overrideAttrs (_: { passthru.shellPath = "/bin/meltype-login"; });
in
{
  # bcon draws through GBM; mesa's GBM backend lives under /run/opengl-driver, which this provides.
  hardware.graphics.enable = true;
  services.seatd.enable = true;
  users.users.meltype = {
    isNormalUser = true;
    description = "Meltype console";
    extraGroups = [ "seat" "video" "input" ];
    # A shell package: NixOS installs it and points passwd at /run/current-system/sw/bin/meltype-login.
    shell = meltypeLogin;
  };
  environment.shells = [ meltypeLogin ];
  # Direct TTY: bcon's own IME stays off; meltype-tty does the conversion.
  environment.etc."bcon/config.toml".text = ''
    [terminal]
    ime = false

    [font]
    main = "${terminalFamily}"
    cjk = "${terminalFamily}"
  '';
  # Noto CJK stays only as fontconfig's fallback for kanji outside PlemolJP's set (IBM Plex Sans JP);
  # it is in the closure anyway as split B's package.nix default font.
  fonts.packages = [ commonFonts pkgs.noto-fonts-cjk-sans ];
  environment.systemPackages = [ bconPackage meltypeTty ];
  # The login's non-console branch, built with the system (a build has no VT): arguments reach bash
  # unchanged, with none it is a login bash, and SHELL is bash so nothing started there re-enters bcon.
  system.checks = [
    (pkgs.runCommand "meltype-login-branches" { } ''
      login=${meltypeLogin}/bin/meltype-login
      [ "$($login -c 'printf "%s|" "$0" "$1"' zero one </dev/null)" = "zero|one|" ]
      [ "$(echo 'shopt -q login_shell && echo login' | $login)" = login ]
      [ "$($login -c 'echo "$SHELL"' </dev/null)" = ${pkgs.bashInteractive}/bin/bash ]
      touch $out
    '')
  ];
}
