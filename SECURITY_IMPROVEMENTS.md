# Security Improvements - Cryptographically Secure Token Generation

## Overview

This document describes the security improvements made to the DazScriptServer plugin's authentication token generation system.

## Problem Statement

The original implementation used Qt 4.8's `qrand()` function to generate API tokens:

```cpp
// OLD IMPLEMENTATION (INSECURE)
qsrand(QDateTime::currentDateTime().toTime_t() ^ (quintptr)this);
for (int i = 0; i < 16; ++i) {
    int randVal = qrand();
    entropyData.append((const char*)&randVal, sizeof(randVal));
}
```

**Security Issues:**
1. `qrand()` is a linear congruential generator (LCG), not cryptographically secure
2. Seed based on timestamp and pointer addresses is partially predictable
3. An attacker with system knowledge could potentially predict or brute-force tokens
4. Tokens are used for authentication - security-critical use case

## Solution

Implemented `SecureRandom` class using platform-specific cryptographic APIs:

### Windows (CryptoAPI)
Uses `CryptGenRandom()` from Windows CryptoAPI:
- Available since Windows 2000
- Uses the operating system's cryptographic random number generator
- Suitable for generating keys, tokens, and other security-critical random data
- No external dependencies (links with `advapi32.lib`)

### Unix/macOS (/dev/urandom)
Uses `/dev/urandom` kernel interface:
- Non-blocking cryptographic pseudorandom number generator
- Suitable for all cryptographic purposes
- Standard on all modern Unix-like systems
- No external dependencies

## Implementation Details

### New Files

**`include/SecureRandom.h`**
- Header-only interface for cryptographically secure random generation
- Platform-agnostic API

**`src/SecureRandom.cpp`**
- Platform-specific implementations
- Windows: CryptoAPI (`CryptGenRandom`)
- Unix/macOS: `/dev/urandom`

### Changes to Existing Code

**`src/DzScriptServerPane.cpp`**
1. Replaced `generateToken()` implementation to use `SecureRandom::generateHexToken()`
2. Added error handling for crypto API failures
3. Added file permission checks (Unix/macOS)
4. Added file permission setting (`chmod 600`) when saving tokens
5. Added validation to prevent server start without valid token

**`src/CMakeLists.txt`**
1. Added `SecureRandom.cpp` to build
2. Added `advapi32.lib` link dependency on Windows

## Security Properties

### Token Generation
- **Entropy**: 128 bits (16 bytes)
- **Format**: 32 hexadecimal characters
- **Source**: OS cryptographic RNG
- **Predictability**: Cryptographically secure (not predictable)

### Token Storage
- **Location**: `~/.daz3d/dazscriptserver_token.txt`
- **Format**: Plain text (one line)
- **Permissions** (Unix/macOS): `0600` (owner read/write only)
- **Permissions** (Windows): Manual restriction recommended

### Token Validation
- Server refuses to start without valid token (when auth enabled)
- Token must be at least 32 characters
- Empty or invalid tokens trigger error messages

## Error Handling

### Crypto API Failure
If the platform crypto API fails:
1. `SecureRandom::generateBytes()` returns empty `QByteArray`
2. `generateToken()` logs error and returns empty `QString`
3. `loadOrGenerateToken()` shows critical error dialog
4. Server refuses to start without valid token

### File Permission Issues
If token file has insecure permissions (Unix/macOS):
- Warning logged at startup
- Includes `chmod` command to fix permissions
- Server still starts (user responsibility to fix)

## Testing

### Unit Test
`test_securerandom.cpp` provides standalone tests:
```bash
# Build (example for macOS)
g++ -o test_securerandom test_securerandom.cpp src/SecureRandom.cpp \
    -I./include -I/path/to/DAZ-SDK/include/QtCore \
    -F/path/to/DAZ-SDK/lib/Mac64 -framework QtCore

# Run
./test_securerandom
```

Tests verify:
- Byte generation works
- Token generation works
- Tokens are correct length (32 hex chars)
- Multiple tokens are unique
- Different sizes work correctly

### Integration Tests
`tests.py` includes authentication tests:
- Token validation
- Header formats (`X-API-Token`, `Authorization: Bearer`)
- Failed authentication logging

## Backward Compatibility

### Token File Format
- **Unchanged**: Still plain text, one line
- Existing tokens remain valid (not regenerated automatically)
- Token length validation updated (32 chars minimum)

### Settings
- No changes to QSettings structure
- Authentication can still be disabled (not recommended)

### API
- No changes to HTTP API
- Same headers supported: `X-API-Token`, `Authorization: Bearer <token>`

## Migration

### Existing Installations
For users with existing tokens:
1. Plugin will load existing token from `~/.daz3d/dazscriptserver_token.txt`
2. If token is valid (≥32 chars), it will be used
3. If token is invalid, new secure token generated

To regenerate token:
1. Click "Regenerate" button in plugin UI, or
2. Delete `~/.daz3d/dazscriptserver_token.txt` and restart plugin

### New Installations
1. Plugin generates secure token on first start
2. Token saved to `~/.daz3d/dazscriptserver_token.txt`
3. File permissions set to `0600` (Unix/macOS)

## Recommendations

### For Users
1. **Keep token secure** - treat it like a password
2. **Restrict file permissions** (Unix/macOS):
   ```bash
   chmod 600 ~/.daz3d/dazscriptserver_token.txt
   ```
3. **Restrict file permissions** (Windows):
   - Right-click file → Properties → Security
   - Remove all users except your account
4. **Regenerate if compromised** - use "Regenerate" button in UI
5. **Enable authentication** - disable only on trusted networks

### For Developers
1. **Never log tokens** - even in debug builds
2. **Use HTTPS** if exposing server to network (requires reverse proxy)
3. **Monitor failed auth attempts** - check request log
4. **Consider IP allowlists** for production deployments

## Future Improvements

### Short Term
1. Windows: Implement proper ACL setting (currently manual)
2. Add token rotation (periodic automatic regeneration)
3. Add token expiration support

### Long Term
1. Support for multiple tokens (per-client)
2. Token revocation list
3. HTTPS support (TLS/SSL)
4. OAuth2/JWT support for enterprise deployments

## References

- [CryptoAPI - CryptGenRandom](https://docs.microsoft.com/en-us/windows/win32/api/wincrypt/nf-wincrypt-cryptgenrandom)
- [/dev/urandom - Linux man page](https://man7.org/linux/man-pages/man4/urandom.4.html)
- [OWASP - Cryptographic Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)

## Changelog

### Version 1.1.0 (2026-03-20)
- Added `SecureRandom` class with platform-specific crypto APIs
- Replaced `qrand()`-based token generation with cryptographically secure generation
- Added file permission checks and setting (Unix/macOS)
- Added error handling for crypto API failures
- Added validation to prevent server start without valid token
- Updated documentation
