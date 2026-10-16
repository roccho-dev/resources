"""One-time source relocation for #25/#31; removed from the delivered tree. No Host effects."""
from pathlib import Path
import shutil, json, sys

W, R, O = map(Path, sys.argv[1:])
assert not O.exists(), "output already exists"
shutil.copytree(R, O)
MAP = [('hosts/common/', 'windows/'), ('hosts/profile/', 'profile/'),
       ('hosts/own/', 'oci/own/'), ('hosts/rent/', 'oci/rent/'), ('infra/', 'extensions/')]

def route(path):
    for before, after in MAP:
        if path.startswith(before):
            return after + path[len(before):]
    return path

def rewrite(text):
    for before, after in MAP:
        text = text.replace(before, after).replace(before.replace('/', '\\'), after.replace('/', '\\'))
    return text

def modify(path, before, after, count=1):
    file = O / path
    text = file.read_text()
    assert text.count(before) == count, (path, before[:60], text.count(before), count)
    file.write_text(text.replace(before, after))

for file in W.rglob('*'):
    if not file.is_file():
        continue
    relative = file.relative_to(W).as_posix()
    if '/bindings/' in relative:
        continue
    target = O / route(relative)
    if relative == '.gitignore':
        target.write_text(target.read_text() + '\nresult*\n_bindings\nci-bindings\n')
        continue
    assert not target.exists(), target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rewrite(file.read_text()))
    target.chmod(file.stat().st_mode & 0o777)

# Provenance labels change; image, volume and auth-target identities do not.
for relative in ['flake.nix', 'oci/own/nix.nix', 'oci/dev/nix.nix']:
    modify(relative, 'Labels."org.opencontainers.image.source" = "https://github.com/roccho-dev/windows";',
           'Labels."org.opencontainers.image.source" = "https://github.com/roccho-dev/resources";')
modify('profile/nix.nix', '../own/codex.nix', '../oci/own/codex.nix')
modify('profile/nix.nix', '../../oci/', '../oci/', 3)
modify('windows/nix.nix', '{ pkgs, source, ownBinding ? builtins.fromJSON (builtins.readFile ../own/bindings/G6I3.json) }:',
       '{ pkgs, source, ownBinding }:')
modify('windows/nix.nix', '../own/spec.json', '../oci/own/spec.json')

# The existing resources font producer becomes the sole implementation.
file = O / 'windows/nix.nix'
text = file.read_text()
start = text.index('  # One selection, reused by Linux')
end = text.index('  python =', start)
text = text[:start] + '  # One implementation, shared with the NixOS console.\n  fonts = (import ../profile/fonts.nix { inherit pkgs; }).commonFonts;\n' + text[end:]
start = text.index('  fonts = pkgs.runCommand')
end = text.index('  dist =', start)
text = text[:start] + text[end:]
text = text.replace('nativeBuildInputs = [ python ]; }', 'nativeBuildInputs = [ python ]; PYTHONPATH = toString ../profile; }')
text = text.replace('    export PYTHONDONTWRITEBYTECODE=1', '    export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=${../profile}')
file.write_text(text)
file = O / 'windows/pack.py'
text = file.read_text()
start = text.index('def prepare_fonts(')
end = text.index('\n\nPACKAGE_KEYS', start)
text = text[:start] + '# Compatibility import: the sole font implementation lives in profile/fonts.py.\nfrom fonts import prepare_fonts\n' + text[end:]
file.write_text(text)

# One flake entry, while retaining both pre-existing package-version locks.
file = O / 'flake.nix'
text = file.read_text()
text = text.replace('description = "own and rent WSLC OCI images"', 'description = "Host tools, native systems and OCI images"')
text = text.replace('  outputs = { self, nixpkgs }:', '''  inputs.host-nixpkgs.url = "github:NixOS/nixpkgs/2efa67fd26b6df417c33e4603185c701f260dd83";
  inputs.host-bindings = { url = "github:roccho-org/envs/1f8a482cbdedc87c8b2a8a84bdbaa28d2497a88e"; flake = false; };
  inputs.bcon = { url = "github:sanohiro/bcon/v1.5.1"; flake = false; };
  inputs.meltype-src = { url = "github:roccho-dev/Meltype/v1.2.1.5"; flake = false; };
  inputs.meltype-linux = { url = "file+https://github.com/roccho-dev/Meltype/releases/download/v1.2.1.5/Meltype-1.2.1.5-linux.zip"; flake = false; };

  outputs = { self, nixpkgs, host-nixpkgs, host-bindings, bcon, meltype-src, meltype-linux }:''')
text = text.replace('      ownOwner = (builtins.fromJSON (builtins.readFile ./oci/own/bindings/G6I3.json)).owner;', '''      # Explicit nonsecret envs input; the Windows library has no target-specific default.
      ownBinding = builtins.fromJSON (builtins.readFile "${host-bindings}/host-bindings/own/G6I3.json");
      ownOwner = ownBinding.owner;''')
text = text.replace('        inherit pkgs;\n        source = self.rev or "uncommitted";', '        inherit pkgs ownBinding;\n        source = self.rev or "uncommitted";')
text = text.replace('    in {\n      inherit releaseVersions;', '    in let producer = {\n      inherit releaseVersions;')
text = text.replace('      packages.${system} = {', '''      packages.${system} = {
        binding-inputs = pkgs.linkFarm "host-binding-inputs" [
          { name = "own.json"; path = "${host-bindings}/host-bindings/own/G6I3.json"; }
          { name = "dev.json"; path = "${host-bindings}/host-bindings/dev/G6I3.json"; }
        ];''', 1)
assert text.endswith('    };\n}\n'), text[-100:]
text = text[:-len('    };\n}\n')] + '''    };
    host = import ./nixos/default.nix {
      inherit self producer bcon meltype-src meltype-linux;
      nixpkgs = host-nixpkgs;
    };
    in nixpkgs.lib.recursiveUpdate producer host;
}
'''
file.write_text(text)

old = (R / 'nixos/flake.nix').read_text()
start = old.index('    let\n')
end = old.rindex('\n}')
text = '{ self, nixpkgs, producer, bcon, meltype-src, meltype-linux }:\n' + old[start:end].rstrip().removesuffix(';') + '\n'
text = text.replace('windows.lib.', 'producer.lib.').replace('windows.releaseVersions', 'producer.releaseVersions')
text = text.replace('inherit bcon meltype-src meltype-linux windows;', 'inherit bcon meltype-src meltype-linux;')
(O / 'nixos/default.nix').write_text(text)
(O / 'nixos/flake.nix').unlink()
(O / 'nixos/flake.lock').unlink()
file = O / 'nixos/meltype-console.nix'
text = file.read_text().replace('# The flake still passes `windows`; only the transitional parity check below reads it (removed with D9).\n', '')
text = text.replace('  imports = [ (import ../profile/fonts-parity.nix { inherit (inputs) windows; }) ];\n', '')
file.write_text(text)
(O / 'profile/fonts-parity.nix').unlink()

# Existing lock entries are reused; actual Nix creates only the new envs lock entry.
windows_lock = json.loads((W / 'flake.lock').read_text())
resources_lock = json.loads((R / 'nixos/flake.lock').read_text())
lock = {'nodes': {'nixpkgs': windows_lock['nodes']['nixpkgs'], 'host-nixpkgs': resources_lock['nodes']['nixpkgs']}, 'root': 'root', 'version': 7}
for key in ['bcon', 'meltype-src', 'meltype-linux']:
    lock['nodes'][key] = resources_lock['nodes'][key]
lock['nodes']['root'] = {'inputs': {key: key for key in lock['nodes']}}
(O / 'flake.lock').write_text(json.dumps(lock, indent=2) + '\n')

modify('oci/dev/proof.sh', 'oci/dev/bindings/G6I3.json', '_bindings/dev.json', 2)
modify('.github/workflows/own-image.yml', 'Get-Content oci/own/bindings/G6I3.json', 'Get-Content _bindings/own.json')
modify('.github/workflows/ci.yml', 'source\\oci\\own\\bindings\\G6I3.json', 'source\\_bindings\\own.json')
for relative in ['.github/workflows/own-image.yml', '.github/workflows/dev-image.yml']:
    file = O / relative
    text = file.read_text()
    needle = '      - uses: cachix/install-nix-action@v31\n'
    assert text.count(needle) == 1
    text = text.replace(needle, needle + '      - run: nix build .#binding-inputs --no-write-lock-file --out-link _bindings\n')
    file.write_text(text)

file = O / '.github/workflows/own-image.yml'
text = file.read_text()
needle = '          old=$(git show "$BASE:oci/own/bindings/G6I3.json" | jq -er .image) || fail \'base binding unreadable\'\n          new=$(jq -er .image oci/own/bindings/G6I3.json) || fail \'binding unreadable\''
assert needle in text
text = text.replace(needle, '''          if git cat-file -e "$BASE:flake.nix" 2>/dev/null; then
            old_input=$(git show "$BASE:flake.lock" | jq -er '.nodes["host-bindings"].locked.rev') || fail 'base input unreadable'
            git fetch --no-tags --depth=1 https://github.com/roccho-org/envs.git "$old_input"
            old=$(git show "$old_input:host-bindings/own/G6I3.json" | jq -er .image) || fail 'base binding unreadable'
          else
            # First relocation only: compare with actual immutable pre-migration evidence.
            baseline=64fe2fb19c756e3439f3549f9020164e69b91b4f
            git fetch --no-tags --depth=1 https://github.com/roccho-dev/windows.git "$baseline"
            old=$(git show "$baseline:hosts/own/bindings/G6I3.json" | jq -er .image) || fail 'migration baseline unreadable'
          fi
          new=$(jq -er .image _bindings/own.json) || fail 'binding unreadable\'''')
file.write_text(text)

file = O / '.github/workflows/ci.yml'
text = file.read_text()
needle = '      - run: nix build .#windows-dist --no-write-lock-file --print-build-logs\n'
assert needle in text
text = text.replace(needle, needle + '''      - run: nix build .#binding-inputs --no-write-lock-file --out-link ci-bindings
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: host-binding-inputs
          path: ci-bindings/own.json
          if-no-files-found: error
          retention-days: 7
''')
needle = '          path: source\n'
assert needle in text
text = text.replace(needle, needle + '''      - uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093
        with:
          name: host-binding-inputs
          path: source/_bindings
''', 1)
file.write_text(text)

file = O / '.github/workflows/own-oci.yml'
text = file.read_text().replace("'nixos/**'", "'nixos/**'\n      - 'flake.nix'\n      - 'flake.lock'\n      - 'oci/**'\n      - 'windows/**'\n      - 'extensions/**'")
text = text.replace('nix flake lock ./nixos --update-input windows', 'nix flake lock .')
text = text.replace('cat nixos/flake.lock', 'cat flake.lock').replace('git diff --exit-code -- nixos/flake.lock', 'git diff --exit-code -- flake.lock')
text = text.replace('nix flake check ./nixos', 'nix flake check .')
file.write_text(text)

# Preserve publication implementation, but leave activation to coordinated M6 acceptance.
for relative in ['.github/workflows/ci.yml', '.github/workflows/release-watch.yml']:
    file = O / relative
    text = file.read_text()
    if relative.endswith('ci.yml'):
        text = text.replace("publish: ${{ github.event_name == 'push'", "publish: ${{ false && github.event_name == 'push'")
        text = text.replace("if: github.event_name == 'push'", "if: false && github.event_name == 'push'")
    else:
        text = text.replace("  schedule:\n    - cron: '0 21 * * 5'\n", '  # Existing cron activates only at the coordinated M6 publisher handoff.\n')
        text = text.replace("if: github.event_name != 'pull_request'", "if: false && github.event_name != 'pull_request'")
    file.write_text(text)
file = O / '.github/workflows/windows-migration.yml'
text = file.read_text().split('\n  # Temporary migration transport only;')[0]
file.write_text(text + '\n')
assert not (O / 'tests/prepare_source.py').exists(), 'transport must not be in delivered source'
print('Prepared tracked files:', len([p for p in O.rglob('*') if p.is_file()]))
