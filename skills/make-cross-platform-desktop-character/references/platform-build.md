# Platform Build

## macOS

1. Require Python 3.12 and run `scripts/setup_environment.sh`.
2. Run `scripts/test_macos.sh`.
3. Build a public package with `scripts/build_macos.sh` or a confirmed local-character package with `scripts/build_macos.sh --include-user-assets`.
4. Verify `dist/XiaoU.app` with a real Cocoa smoke launch and `codesign --verify --deep --strict`.
5. Record the architecture from `uname -m`; do not label an arm64 build as universal.

## Windows

1. Require 64-bit Windows 10/11 and Python 3.12.
2. Run `scripts/setup_environment.ps1` and `scripts/test.ps1`.
3. Build with `scripts/build.ps1`; add `-IncludeUserAssets` only after both approval gates pass.
4. Verify the output contains `dist\\XiaoU\\XiaoU.exe` and the Qt platform plugin.
5. Zip the entire `XiaoU` directory. Never distribute the EXE without its sibling files.

## Release Boundary

Public packages must use `assets/pet/` and exclude `user_assets/`. Local custom packages may include only `user_assets/pet`, the sanitized workflow gate, and an explicitly requested local photo feature. Never include source photos, source sheets, review images, or backups.
