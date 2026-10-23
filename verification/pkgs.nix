# One fixed package universe for the VM and disposable Chrome diagnostic.
import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/1c3fe55ad329cbcb28471bb30f05c9827f724c76.tar.gz";
  sha256 = "sha256-bxrdOn8SCOv8tN4JbTF/TXq7kjo9ag4M+C8yzzIRYbE=";
}) { system = "x86_64-linux"; }
