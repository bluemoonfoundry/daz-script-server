# DazScriptServer Improvement Suggestions

## 1. Security Improvements

### 1.1 Authentication (HIGH PRIORITY)

**Problem**: Currently no authentication - any process on the machine (or network, if host is changed) can execute arbitrary DazScript code.

**Recommended Solution: Static API Token**

Generate a random token on first server start and require it for all `/execute` requests.

**Implementation approach:**
- Generate a cryptographically random token (e.g., 32 hex characters) on first start
- Store in DAZ Studio user data directory: `~/.daz3d/token.txt` or similar
- Add readonly QLineEdit to UI showing the token with a "Copy" button
- Add "Regenerate Token" button for if token is compromised
- Validate token from `X-API-Token` header or `Authorization: Bearer <token>` header
- Return 401 Unauthorized with `{"error": "Invalid or missing API token"}` if missing/wrong

**Why this approach:**
- Simple for users: copy token from UI, paste into client config
- No complex setup (no certificates, passwords, etc.)
- Standard HTTP header-based auth that works with any HTTP client
- Token regeneration capability if compromised
- Low maintenance burden

**Alternative/Complementary: IP Whitelist**
- Add UI field for allowed IPs (comma-separated)
- Default to `127.0.0.1` only
- Reject requests from non-whitelisted IPs with 403 Forbidden
- Useful for local-only restriction even without token auth

**Code changes needed:**
```cpp
// In DzScriptServerPane.h - add members:
QString m_sApiToken;
QLineEdit* m_pTokenEdit;
QPushButton* m_pCopyTokenBtn;
QPushButton* m_pRegenTokenBtn;

// In setupRoutes() - add authentication check:
auto authCheck = [this](const httplib::Request& req) -> bool {
    std::string authHeader = req.get_header_value("X-API-Token");
    if (authHeader.empty())
        authHeader = req.get_header_value("Authorization");
    // Parse "Bearer <token>" if using Authorization header
    return QString::fromStdString(authHeader) == m_sApiToken;
};
```

### 1.2 Input Validation

**Current issues:**
- No validation on script length (could cause memory issues)
- No validation on args complexity (deeply nested objects)
- scriptFile path not sanitized (though DzScript::loadFromFile likely handles this)

**Suggestions:**
- Limit script text length (e.g., 1MB max)
- Limit JSON body size (e.g., 10MB max)
- Add error message if both `scriptFile` and `script` are provided (currently just prefers scriptFile)
- Validate scriptFile is absolute path and exists before passing to DzScript

### 1.3 Security Logging

Add security event logging:
- Failed authentication attempts
- Rejected IPs (if IP whitelist enabled)
- Script execution failures
- Suspicious patterns (rapid requests from same source)

## 2. Reliability Improvements

### 2.1 Memory Leak in stopServer() (CRITICAL)

**Problem**: `m_pServer = new httplib::Server()` in startServer() but only set to nullptr in stopServer() without `delete`.

**Fix:**
```cpp
void DzScriptServerPane::stopServer()
{
    if (!m_bRunning)
        return;

    if (m_pServer) {
        m_pServer->stop();
        delete m_pServer;  // ADD THIS
        m_pServer = nullptr;
    }
    // ... rest of method
}
```

### 2.2 Error Handling in Request Handler

**Current issue**: If JSON parsing fails (malformed JSON), QScriptEngine::evaluate may throw or return invalid value, causing undefined behavior.

**Suggestion:**
```cpp
QScriptValue parsed = parseEngine.evaluate("(" + bodyStr + ")");
if (parseEngine.hasUncaughtException()) {
    QString resp = buildResponseJson(false, QVariant(), QStringList(),
                                     QVariant(QString("Invalid JSON: %1")
                                     .arg(parseEngine.uncaughtException().toString())));
    return resp.toUtf8();
}
```

### 2.3 Request Timeout Configuration

**Current**: Hardcoded 30s read timeout in startServer()

**Suggestion**: Make configurable via UI (default 30s, range 5-300s)
- Useful for long-running scripts that take minutes
- Prevents hung connections

### 2.4 Concurrent Request Handling

**Current limitation**: All requests block on main thread via BlockingQueuedConnection

**Impact**: If script takes 30 seconds to execute, all other requests wait in queue

**Suggestion for future**:
- Add request queue with configurable max concurrent executions
- Show active request count in UI
- Allow request cancellation
- (Note: DazScript execution must still be serialized on main thread, but JSON parsing/validation could happen on worker thread)

### 2.5 Thread Cleanup

**Potential issue**: `m_pServerThread->wait(5000)` might timeout if server is busy

**Suggestion**:
```cpp
if (m_pServerThread) {
    if (!m_pServerThread->wait(5000)) {
        appendLog("Warning: Server thread did not stop cleanly");
        // Consider: m_pServerThread->terminate(); (though risky)
    }
    delete m_pServerThread;
    m_pServerThread = nullptr;
}
```

### 2.6 Rate Limiting

**Problem**: No protection against DoS via rapid requests

**Suggestion**:
- Track requests per IP per time window (e.g., 60 requests/minute)
- Return 429 Too Many Requests when exceeded
- Configurable in UI (default enabled)

## 3. Usability Improvements

### 3.1 Configuration Persistence

**Current**: Host/port don't persist between DAZ Studio sessions

**Suggestion**:
- Save settings to QSettings on change
- Load on startup
- Persist: host, port, token, timeout, rate limit settings

### 3.2 Better Logging

**Current**: Single line per request in small QTextEdit

**Suggestions:**
- Add timestamp to log entries
- Add request duration
- Log IP address of client
- Add "Clear Log" button
- Make log view resizable or scrollable
- Add log level filter (errors only vs all)
- Option to save log to file

Example format:
```
[2026-03-10 14:23:45] [127.0.0.1] [OK] [234ms] CreateBasicCameraSU.dsa
[2026-03-10 14:23:50] [127.0.0.1] [ERR] [12ms] Line 5: Undefined variable
```

### 3.3 Server Auto-start

**Suggestion**: Add checkbox "Start server when pane opens" with persistence

### 3.4 Request Statistics

Add display in UI:
- Total requests served
- Success/failure count
- Average execution time
- Last request timestamp

### 3.5 Port Conflict Handling

**Current**: If port is in use, server fails silently or with obscure error

**Suggestion**: Detect bind failure and show user-friendly error with suggestion to try different port

### 3.6 HTTPS Support (Optional)

**Consideration**: For users who want to expose server to network (not just localhost)

**Approach**:
- Use cpp-httplib's built-in SSL support (requires OpenSSL)
- Self-signed certificate generation
- Show certificate fingerprint in UI for clients to verify
- Probably overkill for most use cases, but worth documenting as future enhancement

## 4. Code Quality Improvements

### 4.1 Separate Concerns

**Current**: DzScriptServerPane handles UI, server lifecycle, request handling, and JSON serialization

**Suggestion**: Extract to separate classes:
- `DzScriptServerCore` - server lifecycle, request handling
- `DzScriptRequestHandler` - script execution logic
- `JsonSerializer` - JSON helpers
- `DzScriptServerPane` - UI only

Benefits: easier testing, cleaner code, reusability

### 4.2 Use Qt's JSON Support

**Current**: Manual JSON serialization via `variantToJson()`

**Suggestion**: Consider using QJsonDocument/QJsonObject (available in Qt 4.8+?)
- Check if DAZ Studio's Qt 4.8 includes QtJson (might be Qt 5+ only)
- If not available, current approach is fine but add unit tests for edge cases

### 4.3 Constants

Extract magic numbers and strings:
```cpp
// Add to header or separate config class
static const int DEFAULT_PORT = 18811;
static const int MIN_PORT = 1024;
static const int MAX_PORT = 65535;
static const int DEFAULT_TIMEOUT_SEC = 30;
static const int THREAD_STOP_TIMEOUT_MS = 5000;
static const char* DEFAULT_HOST = "127.0.0.1";
static const char* TOKEN_FILENAME = "dazscriptserver_token.txt";
```

### 4.4 Error Messages

Make error messages more descriptive:
- Current: "Either scriptFile or script is required"
- Better: "Request must include either 'scriptFile' (path) or 'script' (inline code) field"

## 5. Documentation Improvements

### 5.1 Add Security Section to README

Document:
- Authentication setup process
- Where token is stored
- How to regenerate token
- Best practices (keep localhost-only, don't expose to internet)
- What to do if token is compromised

### 5.2 Add Example Clients

Beyond `test-simple.py`, add examples for:
- Python with authentication
- JavaScript/Node.js
- PowerShell (for Windows pipeline integration)
- C#/.NET (for Unity/Unreal integration)

### 5.3 Update CLAUDE.md with Security Info

Add section on authentication implementation and security considerations.

## Implementation Priority

**High Priority:**
1. Fix memory leak in stopServer() (critical bug)
2. Add API token authentication
3. Add error handling for malformed JSON
4. Configuration persistence

**Medium Priority:**
5. Improve logging (timestamps, duration)
6. Rate limiting
7. Input validation enhancements
8. Better error messages

**Low Priority:**
9. Code refactoring (separate concerns)
10. Request statistics
11. Thread cleanup improvements
12. HTTPS support

## Backward Compatibility Note

Adding authentication is a breaking change for existing clients. Consider:
- Make authentication optional initially (checkbox "Enable API Token")
- Show warning if disabled: "⚠ Authentication disabled - anyone can execute scripts"
- Document migration path for existing deployments
- Or make it required but auto-generate token on first start (print to log)
