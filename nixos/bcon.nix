# Existing upstream renderer; only adapt its login path to NixOS.
{ lib, rustPlatform, pkg-config, makeWrapper, libdrm, libgbm, libglvnd
, libxkbcommon, libinput, systemd, fontconfig, freetype, libseat, shadow }:
let
  src = builtins.fetchGit {
    url = "https://github.com/sanohiro/bcon.git";
    rev = "ca30c939f5ae48fff10eb8dc26ea05b179bef680";
  };
in rustPlatform.buildRustPackage {
  pname = "bcon";
  version = "1.5.1";
  inherit src;
  cargoLock.lockFile = "${src}/Cargo.lock";
  nativeBuildInputs = [ pkg-config makeWrapper ];
  buildInputs = [ libdrm libgbm libxkbcommon libinput systemd fontconfig freetype libseat ];
  postPatch = ''
    substituteInPlace src/terminal/pty.rs --replace-fail '"/bin/login"' '"${shadow}/bin/login"'
  '';
  postFixup = ''
    wrapProgram "$out/bin/bcon" --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath [ libglvnd libseat ]}"
  '';
  meta = { license = lib.licenses.mit; mainProgram = "bcon"; platforms = lib.platforms.linux; };
}
