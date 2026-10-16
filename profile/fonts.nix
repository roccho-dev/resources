# The font selection shared by the Windows host and NixOS: one family per role. The caller's nixpkgs owns font
# versions and upstream content hashes. Moved unchanged from windows hosts/common/nix.nix
# (roccho-dev/resources#25); fonts.py compiles it and its tests run in the same build.
{ pkgs }:
let
  # nixpkgs revisions expose one IBM Plex family either as a passthru (windows' lock) or through the
  # families argument (resources' lock); each selects the IBM Plex Sans JP release that revision pins.
  ibmPlexSansJp = pkgs.ibm-plex.sans-jp or (pkgs.ibm-plex.override { families = [ "sans-jp" ]; });
  choices = [
    {
      role = "ui";
      family = "IBM Plex Sans JP";
      package = ibmPlexSansJp;
      directory = "share/fonts";
    }
    {
      role = "terminal";
      family = "PlemolJP Console NF";
      package = pkgs.plemoljp-nf;
      directory = "share/fonts/truetype/plemoljp-nf-console";
      # The font-only NF release omits a standalone license. Retain the
      # upstream license from the same version; do not weaken the packer gate.
      licenseSource = pkgs.runCommand "plemoljp-license" {} ''
        mkdir -p "$out"
        cp ${pkgs.fetchurl {
          url = "https://raw.githubusercontent.com/yuru7/PlemolJP/v${pkgs.plemoljp-nf.version}/LICENSE";
          sha256 = "52bbb5e729acc62435831d20641ece6a919e610100285ba183ef4d7233fb1e9a";
        }} "$out/LICENSE"
      '';
    }
  ];
  policy = pkgs.writeText "font-selection.json" (builtins.toJSON (map (choice: {
    inherit (choice) role family;
    inherit (choice.package) version;
    directory = "${choice.package}/${choice.directory}";
    licenseSource = toString (choice.licenseSource or choice.package.src);
  }) choices));
  python = pkgs.python3.withPackages (ps: [ ps.fonttools ]);
  commonFonts = pkgs.runCommand "common-fonts" { nativeBuildInputs = [ python ]; } ''
    export PYTHONDONTWRITEBYTECODE=1
    cp ${./fonts.py} fonts.py
    cp ${./test_fonts.py} test_fonts.py
    python -m unittest -v test_fonts
    python fonts.py ${policy} "$out"
  '';
in
{
  inherit choices commonFonts;
}
