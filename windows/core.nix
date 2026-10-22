{ pkgs, meltypeSrc ? null }:
let
  # Version follows the already locked fork source; never a second host pin.
  versionRows = builtins.filter (x: x != null) (map
    (line: builtins.match "[[:space:]]*<Version>([^<]+)</Version>[[:space:]]*" line)
    (pkgs.lib.splitString "\n" (builtins.readFile (meltypeSrc + "/src/Meltype/Meltype.csproj"))));
  meltypeVersion = assert builtins.length versionRows == 1; builtins.head (builtins.head versionRows);
  nocttyVersion = "1.3.131";
in {
  declared = [ "Notepads" "Noctty" "fonts" "Chromium Beta" "Meltype fork" ];
  selected = [ "Notepads" "Noctty" "fonts" "Meltype fork" ];
  pending = [ { product = "Chromium"; channel = "Beta";
    reason = "A true Beta-branch Chromium Windows artifact supplier/build is not selected; Chrome, ungoogled, Stable and arbitrary snapshots are not substitutes."; } ];
  fonts = (import ../profile/fonts.nix { inherit pkgs; }).commonFonts;
  noctty = {
    version = nocttyVersion;
    archive = pkgs.fetchurl {
      url = "https://github.com/amanthanvi/noctty/releases/download/v${nocttyVersion}/noctty-${nocttyVersion}-windows-x64-portable.zip";
      sha256 = "d776bd0e4507abd3a3d6e4a4b347d089960ad5171d0caeeb783e01dd4b0e15fd";
    };
  };
  packages = [ {
    name = "Meltype"; version = meltypeVersion;
    url = "https://github.com/roccho-dev/Meltype/releases/download/v${meltypeVersion}/Meltype-${meltypeVersion}-windows.zip";
    format = "zip"; size = 51260370;
    sha256 = "d4bb334d839712d7a923c1d0a9e5d6943b837d478720a9e80c881539b699efff";
    scope = "user"; effect = "tree-extracted";
    directory = "Programs/meltype-${meltypeVersion}"; executable = "app/Meltype.exe";
    existing = { uninstallKey = "Meltype"; displayName = "Meltype"; publisher = "Yukishiro";
      installLocation = "Programs/Meltype"; executable = "Meltype.exe"; };
    protected = [ "Meltype" ]; appPath = "meltype.exe";
  } ];
  # Store payload bytes are mutable, but the accepted product/publisher/Appx
  # version is explicit. Another version is drift, never silently adopted.
  apps = [ { name = "Notepads"; source = "msstore"; id = "9NHL4NSC67WM";
    package = "19282JackieLiu.Notepads-Beta"; publisherId = "echhpq9pdbte8"; acceptedVersion = "1.5.6.0"; } ];
  typography = { desktop = "ui"; };
}
