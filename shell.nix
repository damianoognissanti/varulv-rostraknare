{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  packages = [
    pkgs.python3
    pkgs.python3Packages.requests
    pkgs.python3Packages.beautifulsoup4
  ];

  shellHook = ''
    echo "Python scraping-miljö laddad."
    python --version
  '';
}
