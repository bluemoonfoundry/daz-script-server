# DazScriptServer Refactoring Plan

## Overview

This document outlines a comprehensive refactoring plan to address code quality, maintainability, and reliability issues identified in the DazScriptServer codebase. The plan is organized into phases to minimize risk and maintain functionality throughout the refactoring process.

## Guiding Principles

1. **Backward Compatibility**: Maintain API compatibility throughout refactoring
2. **Incremental Changes**: Small, testable changes that can be merged frequently
3. **Test Coverage First**: Add tests before refactoring where possible
4. **Documentation**: Update documentation alongside code changes
5. **No Feature Creep**: Focus purely on refactoring, not new features

---

## Phase 1: Foundation & Safety (Weeks 1-2)

**Goal**: Establish testing infrastructure and fix critical thread safety issues.

### 1.1 Testing Infrastructure
- Set up testing framework (Google Test or Qt Test)
- Add CMake test targets
- Create test utilities for mocking DAZ SDK components
- Establish CI pipeline for automated testing

### 1.2 Critical Thread Safety Fixes
- **Priority: CRITICAL**
- Replace `m_nActiveRequests` with `QAtomicInt` or add mutex protection
- Audit all shared state accessed from HTTP threads
- Add thread sanitizer to CI builds
- Document thread safety guarantees for each class

### 1.3 Memory Safety Quick Wins
- Replace raw `new DzScript()` with `QScopedPointer<DzScript>`
- Add RAII wrappers for signal/slot connections
- Fix potential leaks in error paths

**Deliverables**:
- Working test framework with 5+ example tests
- Thread-safe request counter
- Zero memory leaks reported by Valgrind/ASAN
- CI pipeline running on every commit

---

## Phase 2: Extract Core Services (Weeks 3-5)

**Goal**: Break down the god object into focused, testable components.

### 2.1 Authentication Service
Extract authentication logic into `AuthenticationService`:
```cpp
class AuthenticationService {
public:
    explicit AuthenticationService(const QString& tokenFilePath);

    bool validateToken(const QString& token) const;
    QString generateNewToken();
    bool loadToken();
    void saveToken();
    QString currentToken() const;

signals:
    void tokenChanged(const QString& newToken);
    void authenticationFailed(const QString& clientIP);
};
```

**Tests**: Token validation, generation, persistence, concurrency

### 2.2 Rate Limiter Service
Extract rate limiting into `RateLimiterService`:
```cpp
class RateLimiterService {
public:
    RateLimiterService(int maxRequests, int windowSeconds);

    bool checkRateLimit(const QString& clientIP);
    void reset(const QString& clientIP);
    QMap<QString, int> getCurrentLimits() const;

private:
    void cleanup(); // Remove old timestamps
};
```

**Tests**: Rate limit enforcement, sliding window, cleanup, edge cases

### 2.3 IP Whitelist Service
Extract IP filtering into `IPWhitelistService`:
```cpp
class IPWhitelistService {
public:
    explicit IPWhitelistService(const QStringList& allowedIPs);

    bool isAllowed(const QString& clientIP) const;
    void setWhitelist(const QStringList& ips);
    QStringList whitelist() const;
};
```

**Tests**: IP matching, CIDR support (future), wildcard support

### 2.4 Metrics Collector
Extract metrics into `MetricsCollector`:
```cpp
class MetricsCollector {
public:
    void recordRequest(bool success, qint64 durationMs);
    void recordAuthFailure();

    MetricsSnapshot snapshot() const;
    QJsonObject toJson() const;

private:
    mutable QMutex m_mutex;
    RequestMetrics m_metrics;
};
```

**Tests**: Concurrent recording, statistics accuracy, persistence

**Deliverables**:
- 4 new service classes with 80%+ test coverage
- `DzScriptServerPane` reduced by 500+ lines
- All services independently testable

---

## Phase 3: Request Handling Architecture (Weeks 6-8)

**Goal**: Separate HTTP routing from business logic.

### 3.1 Request Handler Interface
Define clean handler interface:
```cpp
class IRequestHandler {
public:
    virtual ~IRequestHandler() = default;
    virtual QByteArray handle(const HttpRequest& req) = 0;
};

struct HttpRequest {
    QByteArray body;
    QString clientIP;
    QMap<QString, QString> headers;
    QMap<QString, QString> queryParams;
};
```

### 3.2 Handler Implementations
Create focused handler classes:
- `ExecuteScriptHandler` - Synchronous script execution
- `AsyncExecuteHandler` - Async script execution
- `ScriptRegistryHandler` - Script registry CRUD
- `StatusHandler` - Health and metrics endpoints
- `AsyncStatusHandler` - Async request status queries

Each handler encapsulates:
- Input validation
- Business logic
- Error handling
- Response formatting

### 3.3 Middleware Chain
Implement middleware pattern for cross-cutting concerns:
```cpp
class Middleware {
public:
    virtual QByteArray process(const HttpRequest& req,
                               std::function<QByteArray()> next) = 0;
};

class AuthenticationMiddleware : public Middleware { /* ... */ };
class RateLimitMiddleware : public Middleware { /* ... */ };
class IPWhitelistMiddleware : public Middleware { /* ... */ };
class LoggingMiddleware : public Middleware { /* ... */ };
class BodySizeMiddleware : public Middleware { /* ... */ };
```

**Deliverables**:
- Handler interface with 5+ implementations
- Middleware chain with 80%+ test coverage
- Route handlers reduced to simple delegation
- Zero code duplication in authentication/validation

---

## Phase 4: Async Execution Subsystem (Weeks 9-10)

**Goal**: Isolate and harden async request queue management.

### 4.1 Async Request Manager
Extract into `AsyncRequestManager`:
```cpp
class AsyncRequestManager : public QObject {
public:
    QString submitRequest(const QString& scriptText, const QVariantMap& args);

    AsyncRequestStatus status(const QString& requestId) const;
    AsyncRequestResult result(const QString& requestId) const;
    bool cancel(const QString& requestId);

    QList<AsyncRequestInfo> listRequests(const QString& statusFilter) const;

signals:
    void requestQueued(const QString& requestId);
    void requestStarted(const QString& requestId);
    void requestCompleted(const QString& requestId);
    void requestFailed(const QString& requestId, const QString& error);
    void requestCancelled(const QString& requestId);

private slots:
    void processNextRequest();
    void cleanupExpiredRequests();
};
```

### 4.2 Bounded Queue Management
Add memory and resource limits:
- Maximum queue depth (reject new requests if full)
- Maximum total requests tracked
- Aggressive TTL-based cleanup
- Memory usage monitoring

### 4.3 Cancellation Protocol
Improve cancellation safety:
- Use atomic flags for cancellation
- Add timeout to killRender() operations
- Better synchronization with main thread
- Cancellation acknowledgment

**Deliverables**:
- `AsyncRequestManager` with comprehensive tests
- Memory bounds enforced
- Graceful degradation under load
- Documented threading model

---

## Phase 5: Error Handling & Validation (Weeks 11-12)

**Goal**: Consistent, robust error handling throughout.

### 5.1 Error Response Framework
Create structured error responses:
```cpp
enum class ErrorCode {
    INVALID_REQUEST,
    AUTHENTICATION_REQUIRED,
    AUTHENTICATION_FAILED,
    RATE_LIMIT_EXCEEDED,
    IP_BLOCKED,
    PAYLOAD_TOO_LARGE,
    SCRIPT_TOO_LONG,
    SERVER_BUSY,
    SCRIPT_EXECUTION_FAILED,
    INTERNAL_ERROR
};

class ErrorResponse {
public:
    static QByteArray create(ErrorCode code,
                             const QString& message,
                             int httpStatus);
    static QByteArray createWithDetails(ErrorCode code,
                                        const QString& message,
                                        const QVariantMap& details,
                                        int httpStatus);
};
```

### 5.2 Input Validation Layer
Centralize validation:
```cpp
class RequestValidator {
public:
    ValidationResult validateExecuteRequest(const QVariantMap& body);
    ValidationResult validateScriptRegistry(const QVariantMap& body);
    ValidationResult validateScriptName(const QString& name);

private:
    int m_maxScriptLength;
    int m_maxBodySize;
};

struct ValidationResult {
    bool valid;
    ErrorCode errorCode;
    QString errorMessage;
};
```

### 5.3 Fail-Fast Initialization
Add startup validation:
- Verify crypto APIs available before starting
- Validate DAZ SDK integration
- Check file system permissions
- Refuse to start if critical components unavailable

**Deliverables**:
- Consistent error responses across all endpoints
- Centralized validation with tests
- Fail-fast behavior for critical errors
- Error code documentation

---

## Phase 6: Code Quality & Documentation (Weeks 13-14)

**Goal**: Eliminate duplication, magic numbers, and improve documentation.

### 6.1 Eliminate Code Duplication
- Remove duplicate `variantToJson()` implementations
- Extract common route handler patterns
- Consolidate JSON response building
- Share authentication logic

### 6.2 Named Constants
Extract all magic numbers to configuration:
```cpp
namespace RequestConfig {
    constexpr int ASYNC_STATUS_POLL_INTERVAL_MS = 500;
    constexpr int REQUEST_ID_LENGTH = 8;
    constexpr int METRICS_SAVE_INTERVAL = 10;
    constexpr int ASYNC_CLEANUP_INTERVAL_MIN = 5;
    constexpr int ASYNC_REQUEST_TTL_HOURS = 1;
}
```

### 6.3 Comprehensive Documentation
- API documentation for all public classes
- Threading model documentation per class
- Error handling guide for API consumers
- Architecture decision records (ADRs)
- Updated README with architecture diagrams

### 6.4 Code Style Consistency
- Run clang-format across codebase
- Fix naming inconsistencies
- Standardize include order
- Remove commented-out code

**Deliverables**:
- Zero code duplication detected by static analysis
- All magic numbers converted to named constants
- 100% public API documentation coverage
- Architecture documentation updated

---

## Phase 7: Settings & Configuration (Week 15)

**Goal**: Robust, validated settings management.

### 7.1 Settings Service
Centralize settings management:
```cpp
class SettingsService {
public:
    static SettingsService& instance();

    ServerSettings loadSettings();
    void saveSettings(const ServerSettings& settings);
    void migrateSettings(int fromVersion, int toVersion);

    ValidationResult validate(const ServerSettings& settings);

private:
    ServerSettings m_currentSettings;
    QMutex m_mutex;
};

struct ServerSettings {
    QString host;
    int port;
    bool authEnabled;
    bool ipWhitelistEnabled;
    QStringList allowedIPs;
    bool rateLimitEnabled;
    int rateLimitMax;
    int rateLimitWindowSec;
    int maxConcurrentRequests;
    int maxBodySizeMB;
    int maxScriptLengthKB;
    int version;  // Settings schema version
};
```

### 7.2 Settings Migration
- Version settings schema
- Provide migration paths for upgrades
- Validate loaded settings
- Fallback to defaults on corruption

**Deliverables**:
- Centralized settings service
- Settings validation
- Migration framework
- Settings persistence tests

---

## Phase 8: Platform & Security Hardening (Week 16)

**Goal**: Robust platform-specific code and security improvements.

### 8.1 Crypto Error Handling
- Retry with alternative sources on failure
- Log detailed crypto errors
- Refuse to start server if crypto unavailable
- Add periodic crypto health checks

### 8.2 Resource Cleanup Hardening
- Add timeouts to all blocking operations
- Implement graceful shutdown with deadlines
- Clean up dangling resources on error paths
- Add resource usage monitoring

### 8.3 Unicode & Encoding
- Standardize on UTF-8 throughout
- Validate input encoding
- Document encoding assumptions
- Add encoding tests

**Deliverables**:
- Robust crypto initialization
- No indefinite blocking operations
- UTF-8 consistency
- Platform-specific code tested on Windows/macOS/Linux

---

## Phase 9: Integration & Performance Testing (Week 17)

**Goal**: Comprehensive end-to-end testing and performance validation.

### 9.1 Integration Tests
- Full HTTP request/response tests
- Multi-threaded stress tests
- Authentication flow tests
- Async execution tests
- Error scenario tests

### 9.2 Performance Benchmarks
- Measure request throughput
- Test under concurrent load
- Memory usage profiling
- Long-running render tests
- Resource leak detection

### 9.3 Load Testing
- Simulate realistic workloads
- Test rate limiting under load
- Verify graceful degradation
- Measure recovery time

**Deliverables**:
- Integration test suite with 50+ tests
- Performance benchmarks baseline
- Load testing results documented
- No regressions vs. baseline

---

## Phase 10: Documentation & Release (Week 18)

**Goal**: Complete documentation and prepare for release.

### 10.1 API Documentation
- OpenAPI/Swagger specification
- Client examples in multiple languages
- Error handling guide
- Best practices documentation

### 10.2 Architecture Documentation
- System architecture diagrams
- Threading model diagrams
- Component interaction diagrams
- Deployment guide

### 10.3 Migration Guide
- Guide for users upgrading from v1.x
- Breaking changes documentation
- Configuration migration steps
- Troubleshooting guide

### 10.4 Release Preparation
- Changelog generation
- Version bump
- Release notes
- Backward compatibility verification

**Deliverables**:
- Complete API documentation
- Architecture documentation
- Migration guide
- v2.0 release candidate

---

## Success Metrics

### Code Quality
- **Test Coverage**: >80% line coverage, >90% branch coverage for new code
- **Code Duplication**: <3% (measured by CPD or similar)
- **Cyclomatic Complexity**: No functions >15, average <5
- **Lines per Class**: Main pane class <500 lines (from 2376)

### Reliability
- **Thread Safety**: Zero data races detected by thread sanitizer
- **Memory Safety**: Zero leaks detected by Valgrind/ASAN
- **Resource Cleanup**: All resources cleaned up within 5s of shutdown
- **Error Handling**: 100% of error paths tested

### Performance
- **No Regressions**: Performance within 5% of baseline
- **Concurrent Requests**: Handle 50+ concurrent requests without degradation
- **Memory Growth**: <10MB growth over 1000 requests
- **Startup Time**: <1 second from launch to ready

### Maintainability
- **Build Time**: <5 minutes clean build
- **Test Time**: <30 seconds for full test suite
- **Documentation**: 100% public API documented
- **New Contributor Onboarding**: <2 hours to first contribution

---

## Risk Management

### High-Risk Changes
1. **Threading Model Changes**: Extensive testing required
2. **HTTP Library Updates**: May break existing clients
3. **Settings Migration**: Data loss potential

**Mitigation**: Feature flags, extensive testing, backup/restore functionality

### Rollback Strategy
- Maintain v1.x branch for critical fixes
- Feature flags for new architecture
- Automated rollback in CI/CD
- Database migration reversibility

### Dependency Management
- Pin dependency versions
- Regular security updates
- Dependency vulnerability scanning
- License compliance checks

---

## Timeline Summary

| Phase | Duration | Dependencies | Risk |
|-------|----------|--------------|------|
| 1. Foundation & Safety | 2 weeks | None | Medium |
| 2. Extract Core Services | 3 weeks | Phase 1 | Low |
| 3. Request Handling | 3 weeks | Phase 2 | Medium |
| 4. Async Subsystem | 2 weeks | Phase 3 | High |
| 5. Error Handling | 2 weeks | Phase 3 | Low |
| 6. Code Quality | 2 weeks | All above | Low |
| 7. Settings | 1 week | Phase 2 | Low |
| 8. Platform Hardening | 1 week | Phase 7 | Medium |
| 9. Integration Testing | 1 week | All above | Low |
| 10. Documentation | 1 week | All above | Low |

**Total Duration**: ~18 weeks (4.5 months)

---

## Open Questions

1. Should we support breaking changes in v2.0 or maintain full backward compatibility?
2. What's the minimum supported DAZ Studio version after refactoring?
3. Should we add a plugin upgrade mechanism?
4. Do we need to support downgrading from v2.0 to v1.x?
5. Should async requests persist across server restarts?

---

## Conclusion

This refactoring plan addresses all identified code quality issues while maintaining functionality and minimizing risk. The phased approach allows for incremental progress with regular validation checkpoints. Each phase delivers tangible improvements that can be released independently if needed.

**Estimated Effort**: 4-5 months with 1 full-time developer, or 2-3 months with 2 developers working in parallel on independent phases.
