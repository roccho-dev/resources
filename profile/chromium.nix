# Official best-effort Chromium snapshots, selected once and then immutable inputs.
# These are different OS builds, not Chrome channel releases and not a moving latest.
{ pkgs }:
let
  selections = {
    windows = {
      revision = "1725461"; productVersion = "158.0.8120.0";
      sourceCommit = "de870ab4e5458d2efb17be9070932318dfb43019";
      size = 368715830; sha256 = "10b934a9178ec2788d0cbadaf6a5bb179907ad42c06153174052f24fdbd48cba";
    };
    linux = {
      revision = "1725409"; productVersion = "158.0.8119.0";
      sourceCommit = "2fd190223685b6c8fbe3723772c28b2797a675aa";
      size = 253847229; sha256 = "6086e166e5a41a52346a2a163acf47a991643592a4d83f375bf0284a223620dd";
    };
  };
  pins = builtins.mapAttrs (os: pin:
    assert builtins.match "[1-9][0-9]*" pin.revision != null;
    assert builtins.match "[0-9]+(\\.[0-9]+){3}" pin.productVersion != null;
    assert builtins.match "[0-9a-f]{40}" pin.sourceCommit != null;
    pin // {
      url = "https://storage.googleapis.com/chromium-browser-snapshots/"
        + (if os == "windows" then "Win_x64" else "Linux_x64")
        + "/${pin.revision}/" + (if os == "windows" then "chrome-win.zip" else "chrome-linux.zip");
    }) selections;
  # Both selected source revisions carry the same BSD notice. Keep it with each
  # materialization; the unchanged browser resources also contain chrome://credits.
  license = pkgs.runCommand "chromium-source-license" {} ''
    ${pkgs.coreutils}/bin/base64 -d ${pkgs.fetchurl {
      url = "https://chromium.googlesource.com/chromium/src/+/${pins.windows.sourceCommit}/LICENSE?format=TEXT";
      sha256 = "363eddfec00830d4826f38173bd40a17eeada40a947a8d93b935371a1ae5a6d1";
    }} > "$out"
  '';
  win = pins.windows;
  windowsPackage = {
    name = "Chromium"; version = "${win.productVersion}.r${win.revision}";
    inherit (win) productVersion url size sha256;
    format = "zip"; scope = "user"; effect = "tree-extracted";
    directory = "Programs/chromium-${win.productVersion}.r${win.revision}";
    executable = "chrome-win/chrome.exe";
    existing = { uninstallKey = "Chromium"; displayName = "Chromium"; publisher = "The Chromium Authors";
      installLocation = "Chromium/Application"; executable = "chrome.exe"; };
    protected = [ "Chromium/User Data" ];
    seed = { path = "chrome-win/initial_preferences"; fonts = { proportional = "ui"; fixed = "terminal"; }; };
    appPath = "chromium.exe";
  };
  runtime = with pkgs; [
    alsa-lib at-spi2-atk at-spi2-core cups dbus expat glib gtk3 nspr nss pango
    libdrm libxkbcommon mesa stdenv.cc.cc.lib systemd zlib
    xorg.libX11 xorg.libXcomposite xorg.libXdamage xorg.libXext xorg.libXfixes
    xorg.libXrandr xorg.libxcb
  ];
  linux = pkgs.stdenvNoCC.mkDerivation {
    pname = "chromium-snapshot"; version = "${pins.linux.productVersion}.r${pins.linux.revision}";
    src = pkgs.fetchurl { inherit (pins.linux) url sha256; };
    nativeBuildInputs = [ pkgs.unzip pkgs.autoPatchelfHook pkgs.makeWrapper pkgs.python3 ];
    buildInputs = runtime;
    sourceRoot = "chrome-linux";
    dontConfigure = true; dontBuild = true; dontStrip = true;
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/lib/chromium" "$out/bin" "$out/share/licenses/chromium" "$out/share/chromium"
      cp -a . "$out/lib/chromium/"
      # No setuid sandbox installation or sandbox-disabling switch.
      chmod 755 "$out/lib/chromium/chrome" "$out/lib/chromium/chrome_sandbox" "$out/lib/chromium/chrome_crashpad_handler"
      cp ${license} "$out/share/licenses/chromium/LICENSE"
      cp ${./chromium-proof.py} "$out/share/chromium/chromium-proof.py"
      makeWrapper "$out/lib/chromium/chrome" "$out/bin/chromium-snapshot" \
        --prefix LD_LIBRARY_PATH : "${pkgs.lib.makeLibraryPath runtime}"
      runHook postInstall
    '';
    # autoPatchelf runs in fixup hooks; attest only after the complete phase.
    postPhases = [ "snapshotIdentityPhase" ];
    snapshotIdentityPhase = ''
      export CHROMIUM_OUT="$out"
      python - <<'PY'
import hashlib,json,os,pathlib
root=pathlib.Path(os.environ["CHROMIUM_OUT"])
p=json.loads(${builtins.toJSON (builtins.toJSON pins.linux)})
p.update(executable=str(root/"lib/chromium/chrome"),
         executableSha256=hashlib.file_digest((root/"lib/chromium/chrome").open("rb"),"sha256").hexdigest(),
         launcher=str(root/"bin/chromium-snapshot"), architecture="x86_64",
         proofSha256=hashlib.sha256((root/"share/chromium/chromium-proof.py").read_bytes()).hexdigest())
(root/"share/chromium/snapshot.json").write_text(json.dumps(p,sort_keys=True,indent=2)+"\n")
PY
    '';
    meta = { description = "Fixed official Chromium Snapshot; normal sandbox required";
      platforms = [ "x86_64-linux" ]; license = pkgs.lib.licenses.bsd3; };
  };
in { inherit pins license windowsPackage linux; }
