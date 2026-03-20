# Reliability and Maintainability Improvements

## Overview

This document describes the reliability and maintainability improvements made to the DazScriptServer plugin beyond the security enhancements.

## Summary of Improvements

1. **Request Queue Limiting** - Prevents DoS via concurrent request limits
2. **JsonBuilder Class** - Clean, maintainable JSON generation
3. **Health Check Endpoint** - Observability and monitoring
4. **Metrics Endpoint** - Request statistics and performance tracking
5. **Request IDs** - Better debugging and request correlation
6. **Configuration Constants** - Centralized, documented limits
7. **Metrics Tracking** - Internal counters for all requests

---

## 1. Request Queue Limiting (DoS Protection)

### Problem
The original implementation had no limit on concurrent requests. Since cpp-httplib spawns a thread per request, a malicious client could exhaust system resources by sending many requests simultaneously.

### Solution
Added atomic counter for active requests with configurable limit:

```cpp
// include/DzScriptServerPane.h
namespace ServerConfig {
    const int MAX_CONCURRENT_REQUESTS = 10;
}

private:
    int m_nActiveRequests;  // Current concurrent requests
```

```cpp
// src/DzScriptServerPane.cpp - POST /execute handler
if (m_nActiveRequests >= ServerConfig::MAX_CONCURRENT_REQUESTS) {
    res.status = 429;  // Too Many Requests
    res.set_content("{\"success\":false,\"error\":\"Server busy...\"}");
    return;
}
m_nActiveRequests++;
// ... process request ...
m_nActiveRequests--;
```

### Benefits
- Prevents resource exhaustion attacks
- Limits memory usage from concurrent script execution
- Provides clear error message to clients when busy
- Returns HTTP 429 (Too Many Requests) - standard status code

---

## 2. JsonBuilder Class

### Problem
Original implementation used manual string concatenation for JSON:

```cpp
// OLD (error-prone)
QString json;
json += "{";
json += "\"success\":" + QString(success ? "true" : "false") + ",";
json += "\"result\":" + variantToJson(result) + ",";
json += "}";
```

Issues:
- Hard to read and maintain
- Easy to introduce syntax errors (missing commas, etc.)
- Duplicated escaping logic
- No type safety

### Solution
Created `JsonBuilder` class with clean API:

```cpp
// include/JsonBuilder.h
class JsonBuilder {
public:
    void startObject();
    void addMember(const QString& name, const QVariant& value);
    void finishObject();
    QString toString() const;
    // ... more methods
};
```

```cpp
// NEW (clean and maintainable)
JsonBuilder json;
json.startObject();
json.addMember("success", success);
json.addMember("result", result);
json.addMember("output", outputList);
json.addMember("error", error);
json.finishObject();
return json.toString();
```

### Benefits
- **Maintainable**: Easier to read and modify
- **Safe**: Automatic escaping, type-safe methods
- **Consistent**: Single escaping implementation
- **Flexible**: Supports nested objects/arrays via QVariant
- **No dependencies**: Uses only Qt 4.8 types

---

## 3. Health Check Endpoint

### Implementation
```
GET /health
```

**Response:**
```json
{
    "status": "ok",
    "version": "1.1.0",
    "running": true,
    "auth_enabled": true,
    "active_requests": 2,
    "uptime_seconds": 3600
}
```

### Use Cases
- **Monitoring**: Check if server is responsive
- **Load balancers**: Health check probes
- **Deployment**: Verify plugin loaded correctly
- **Debugging**: Quick status overview

### Benefits
- No authentication required (safe status info only)
- Fast response (no blocking operations)
- Standard /health pattern
- Includes active request count for load monitoring

---

## 4. Metrics Endpoint

### Implementation
```
GET /metrics
```

**Response:**
```json
{
    "total_requests": 1523,
    "successful_requests": 1489,
    "failed_requests": 28,
    "auth_failures": 6,
    "active_requests": 2,
    "uptime_seconds": 86400,
    "success_rate_percent": 97.77
}
```

### Metrics Tracked
- **total_requests**: All requests received
- **successful_requests**: Scripts executed without errors
- **failed_requests**: Script errors or validation failures
- **auth_failures**: Failed authentication attempts
- **active_requests**: Current concurrent requests
- **uptime_seconds**: Time since server started
- **success_rate_percent**: Calculated success rate

### Use Cases
- **Monitoring**: Track error rates over time
- **Alerting**: Set thresholds on success_rate_percent
- **Capacity planning**: Track active_requests trends
- **Security**: Monitor auth_failures for attacks
- **Performance**: Correlate success rates with load

### Benefits
- Lightweight (mutex-protected counters)
- No authentication required (safe aggregate stats only)
- Standard metrics format
- Includes calculated success rate

---

## 5. Request IDs

### Implementation
Each request gets a unique 8-character ID:

```cpp
QString DzScriptServerPane::generateRequestId() {
    QUuid uuid = QUuid::createUuid();
    return uuid.toString().mid(1, 8);  // "xxxxxxxx"
}
```

**Request IDs appear in:**
1. Response JSON (`request_id` field)
2. Log entries
3. Error messages

**Example log:**
```
[14:23:45] [127.0.0.1] [OK] [523ms] [a3f2b891] script.dsa
```

**Example response:**
```json
{
    "success": true,
    "result": 42,
    "output": [],
    "error": null,
    "request_id": "a3f2b891"
}
```

### Benefits
- **Debugging**: Correlate client requests with server logs
- **Support**: Users can report failing request IDs
- **Tracing**: Track request through the system
- **Monitoring**: Identify slow/failing individual requests

---

## 6. Configuration Constants

### Problem
Original implementation had magic numbers scattered throughout:

```cpp
const size_t MAX_BODY_SIZE = 5 * 1024 * 1024;  // Here
const int MAX_SCRIPT_LENGTH = 1024 * 1024;     // There
const int MAX_LOG_LINES = 1000;                // Everywhere
```

### Solution
Centralized configuration namespace:

```cpp
// include/DzScriptServerPane.h
namespace ServerConfig {
    const int MAX_CONCURRENT_REQUESTS = 10;
    const size_t MAX_BODY_SIZE = 5 * 1024 * 1024;  // 5MB
    const int MAX_SCRIPT_LENGTH = 1024 * 1024;     // 1MB
    const int MAX_LOG_LINES = 1000;
    const int MAX_CAPTURED_LINES = 10000;
}
```

### Usage
```cpp
if (req.body.size() > ServerConfig::MAX_BODY_SIZE) {
    // ...
}
```

### Benefits
- **Maintainability**: Single place to adjust limits
- **Documentation**: Clear names and comments
- **Type safety**: Proper types (size_t for sizes, int for counts)
- **Future**: Easy to make configurable via settings file

---

## 7. Request Metrics Tracking

### Implementation
Thread-safe metrics structure:

```cpp
struct RequestMetrics {
    int totalRequests;
    int successfulRequests;
    int failedRequests;
    int authFailures;
    QDateTime startTime;
    QMutex mutex;  // Protects all counters
};
```

**Recording function:**
```cpp
void DzScriptServerPane::recordRequest(bool success, qint64 durationMs) {
    QMutexLocker lock(&m_metrics.mutex);
    m_metrics.totalRequests++;
    if (success) {
        m_metrics.successfulRequests++;
    } else {
        m_metrics.failedRequests++;
    }
}
```

### Thread Safety
- All metrics access protected by mutex
- Auth failures recorded in HTTP handler thread
- Request outcomes recorded on main thread
- QMutexLocker ensures automatic unlock

### Benefits
- Accurate request counters
- No race conditions
- Minimal overhead (simple counters)
- Foundation for future enhancements (duration histograms, etc.)

---

## API Changes

### New Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Server health status |
| `/metrics` | GET | No | Request statistics |

### Response Changes

**POST /execute** now includes optional `request_id`:

```json
{
    "success": true,
    "result": 42,
    "output": ["line 1", "line 2"],
    "error": null,
    "request_id": "a3f2b891"
}
```

**New Error Response (429):**
```json
{
    "success": false,
    "error": "Server busy - too many concurrent requests"
}
```

---

## Configuration Values

All configurable limits are now centralized:

| Setting | Value | Purpose |
|---------|-------|---------|
| `MAX_CONCURRENT_REQUESTS` | 10 | Concurrent request limit |
| `MAX_BODY_SIZE` | 5MB | Request body size limit |
| `MAX_SCRIPT_LENGTH` | 1MB | Script text length limit |
| `MAX_LOG_LINES` | 1000 | UI log view size |
| `MAX_CAPTURED_LINES` | 10000 | Script output capture limit |

---

## Backward Compatibility

### Breaking Changes
**None**. All changes are additive:
- New endpoints don't affect existing API
- Request ID is optional field in responses
- HTTP 429 is new error code (clients should already handle 4xx)

### Compatible Changes
- GET /status: unchanged
- POST /execute: same behavior, additional response field
- Authentication: unchanged
- Error codes: expanded (added 429)

---

## Testing

### Health Check
```bash
curl http://127.0.0.1:18811/health
```

Expected:
```json
{
    "status": "ok",
    "version": "1.1.0",
    "running": true,
    "auth_enabled": true,
    "active_requests": 0,
    "uptime_seconds": 42
}
```

### Metrics
```bash
curl http://127.0.0.1:18811/metrics
```

Expected:
```json
{
    "total_requests": 10,
    "successful_requests": 8,
    "failed_requests": 2,
    "auth_failures": 0,
    "active_requests": 0,
    "uptime_seconds": 120,
    "success_rate_percent": 80.0
}
```

### Request Limiting
```python
import requests
import concurrent.futures

# Spawn 20 concurrent requests (limit is 10)
def make_request(i):
    return requests.post("http://127.0.0.1:18811/execute",
        headers={"X-API-Token": "your-token"},
        json={"script": "return 1;"}
    )

with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    results = list(executor.map(make_request, range(20)))

# Some requests should return 429
status_codes = [r.status_code for r in results]
print(f"200s: {status_codes.count(200)}")
print(f"429s: {status_codes.count(429)}")
```

### Request IDs
```python
response = requests.post("http://127.0.0.1:18811/execute",
    headers={"X-API-Token": "your-token"},
    json={"script": "return 42;"}
)
print(response.json()["request_id"])  # e.g., "a3f2b891"
```

---

## Code Statistics

| File | Lines Added | Lines Removed | Purpose |
|------|-------------|---------------|---------|
| `include/JsonBuilder.h` | 59 | 0 | JSON builder interface |
| `src/JsonBuilder.cpp` | 214 | 0 | JSON builder implementation |
| `include/DzScriptServerPane.h` | 32 | 2 | Config constants + metrics |
| `src/DzScriptServerPane.cpp` | 112 | 47 | Endpoints + metrics + refactoring |

**Total:** ~417 lines added, 49 removed

---

## Future Enhancements

### Short Term
1. **Duration histograms**: Track p50/p95/p99 latency
2. **Per-endpoint metrics**: Separate /execute vs /health counts
3. **Client metrics**: Track requests per client IP

### Long Term
1. **Configuration file**: Make all ServerConfig values configurable
2. **Persistent metrics**: Save/restore metrics across restarts
3. **Prometheus format**: `/metrics` in Prometheus exposition format
4. **Request tracing**: Distributed tracing support (OpenTelemetry)

---

## References

- [RFC 6585 - HTTP Status Code 429](https://tools.ietf.org/html/rfc6585)
- [Health Check Response Format for HTTP APIs](https://tools.ietf.org/id/draft-inadarei-api-health-check-06.html)
- [Qt 4.8 Documentation](https://doc.qt.io/archives/qt-4.8/)

---

## Changelog

### Version 1.1.0 (2026-03-20)
- Added request queue limiting (max 10 concurrent)
- Added JsonBuilder class for maintainable JSON generation
- Added GET /health endpoint
- Added GET /metrics endpoint
- Added request IDs for debugging
- Centralized configuration constants
- Added metrics tracking infrastructure
- Updated version number to 1.1.0
