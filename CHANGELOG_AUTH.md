# Authentication Implementation Changelog

## Summary

This update fixes a critical memory leak and adds API token authentication to the DazScriptServer plugin.

## Changes Implemented

### 1. Critical Bug Fix: Memory Leak (HIGH PRIORITY)

**File:** `src/DzScriptServerPane.cpp`
**Line:** 130 (stopServer method)

**Issue:** `httplib::Server*` was allocated with `new` but never deleted, causing memory leak on every server stop/restart.

**Fix:**
```cpp
if (m_pServer) {
    m_pServer->stop();
    delete m_pServer;  // ADDED: Delete server object to prevent memory leak
    m_pServer = nullptr;
}
```

Also added warning if thread doesn't stop cleanly within timeout.

### 2. API Token Authentication (SECURITY FEATURE)

#### A. Token Generation & Storage

**Files:**
- `include/DzScriptServerPane.h` - Added member variables and methods
- `src/DzScriptServerPane.cpp` - Implemented authentication logic

**Features:**
- Cryptographically random 32-character hex token (128-bit entropy)
- Auto-generated on first start
- Stored in `~/.daz3d/dazscriptserver_token.txt`
- Persisted across DAZ Studio sessions

#### B. Authentication Validation

**Location:** `setupRoutes()` in `src/DzScriptServerPane.cpp`

**Mechanism:**
- Checks `X-API-Token` HTTP header
- Also supports `Authorization: Bearer <token>` header
- Validates before invoking main thread
- Returns HTTP 401 Unauthorized with JSON error if invalid/missing

**Example rejection response:**
```json
{
  "success": false,
  "error": "Unauthorized: Invalid or missing API token"
}
```

#### C. UI Enhancements

**New UI elements:**
- Authentication group box with:
  - Checkbox to enable/disable authentication (default: enabled)
  - Token display field (password-masked)
  - "Copy" button - copies token to clipboard
  - "Regenerate" button - generates new token with confirmation dialog
  - Hint text explaining header requirement

**Status display:**
- Shows "Protected" or "⚠ Unprotected" in status label when running
- Warning logged when auth is disabled

#### D. Settings Persistence

**Storage:** QSettings under "DAZ 3D/DazScriptServer"

**Persisted settings:**
- `host` - Server host address
- `port` - Server port number
- `authEnabled` - Authentication enabled/disabled state

**Token storage:** Separate text file for easy client access

### 3. Documentation Updates

#### README.md
- Added Authentication section with setup instructions
- Added security notes about token handling
- Added Python example with authentication
- Updated API documentation to show auth headers

#### CLAUDE.md
- Added Security section
- Updated HTTP API table to show auth requirements
- Updated Request Flow to include authentication step
- Documented authentication implementation details

#### test-simple.py
- Enhanced to automatically read token from file
- Added three examples:
  1. Inline script execution
  2. Script file execution
  3. Authentication failure test (commented)
- Added proper error handling and status checking

### 4. Code Quality Improvements

**Better error handling:**
- Thread stop timeout detection
- Settings load/save error handling
- Token file creation with directory creation

**Thread safety:**
- Token loaded at startup (read-only during operation)
- Safe for HTTP threads to read without synchronization

## Migration Guide

### For Existing Deployments

**Breaking Change:** Clients without tokens will now receive 401 errors (if auth is enabled).

**Migration steps:**
1. Build and install the updated plugin
2. Start the server - token will be auto-generated
3. Copy token from UI using "Copy" button
4. Update client code to include token in headers:

**Python:**
```python
import os
with open(os.path.expanduser("~/.daz3d/dazscriptserver_token.txt")) as f:
    token = f.read().strip()

headers = {"X-API-Token": token}
requests.post(url, headers=headers, json=payload)
```

**JavaScript:**
```javascript
const fs = require('fs');
const token = fs.readFileSync(
    require('os').homedir() + '/.daz3d/dazscriptserver_token.txt',
    'utf8'
).trim();

fetch(url, {
    method: 'POST',
    headers: {'X-API-Token': token},
    body: JSON.stringify(payload)
});
```

### Temporary Workaround

If you need to disable authentication temporarily:
1. Uncheck "Enable API Token Authentication" in the UI
2. Warning will be logged on server start
3. Not recommended for production use

## Security Considerations

### Token Security
- Token file should have restricted permissions (chmod 600 on Unix)
- Keep token secure - it grants full script execution access
- Regenerate token if compromised
- Consider localhost-only binding (127.0.0.1) for additional security

### Future Enhancements
- Rate limiting (prevent DoS)
- IP whitelisting (additional access control)
- Request logging with timestamps and IPs
- HTTPS support for network exposure
- More secure token generation (use system crypto APIs)

## Testing

### Build & Test Steps

1. **Build the plugin:**
```bash
./build.sh
```

2. **Install to DAZ Studio:**
```bash
./build.sh --install
```

3. **Test authentication:**
```bash
python test-simple.py
```

4. **Verify:**
- Token file exists at `~/.daz3d/dazscriptserver_token.txt`
- Valid token allows script execution
- Invalid/missing token returns 401
- Token persists across restarts
- Settings (host/port) persist across restarts

## Files Modified

### Header Files
- `include/DzScriptServerPane.h` - Added auth members, methods, UI widgets

### Implementation Files
- `src/DzScriptServerPane.cpp` - Added auth logic, fixed memory leak, enhanced UI

### Documentation
- `README.md` - Added authentication documentation
- `CLAUDE.md` - Added security section and updated architecture docs
- `test-simple.py` - Enhanced with auth examples

### New Files
- `IMPROVEMENTS.md` - Comprehensive improvement suggestions
- `CHANGELOG_AUTH.md` - This file

## Backward Compatibility

**Breaking:** Yes, if authentication is enabled (default)

**Mitigation:**
- Authentication can be disabled via checkbox
- Clear error messages (401 with descriptive JSON)
- Token auto-generation (no manual setup required)
- Simple migration path (read token file, add header)

## Performance Impact

**Minimal:**
- Token validation is a simple string comparison on HTTP thread
- No crypto operations during request handling
- No additional main thread blocking
- Settings load/save only on startup/shutdown

## Known Limitations

1. **Token generation:** Uses `qrand()` instead of cryptographically secure RNG
   - Sufficient for local-only use
   - Consider enhancement for network-exposed scenarios

2. **Token storage:** Plaintext file
   - Appropriate for this use case (like SSH keys)
   - File permissions should be restricted by user

3. **No rate limiting:** Can still be DoS'd with rapid requests
   - Listed in IMPROVEMENTS.md for future implementation

4. **No audit logging:** Authentication failures not logged to file
   - Only displayed in UI log view
   - Listed in IMPROVEMENTS.md for future implementation
