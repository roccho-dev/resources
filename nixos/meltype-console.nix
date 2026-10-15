# Japanese input on VersaPro's physical console: fork Meltype's Direct TTY (meltype-tty) inside bcon.
# Use: log in as `meltype` on a getty VT -> `bcon --backend=seatd` -> inside bcon `meltype-tty --raw-text`.
# No system service, no login-shell change, no password or other secret (the User sets it on the host).
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
  # Split B's own package expression, fed with the same release's Linux zip (unpacked by the input).
  meltypeTty = import "${meltype-src}/linux/tty/package.nix" {
    inherit pkgs;
    packagePath = "${meltype-linux}";
  };
in
{
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
}
