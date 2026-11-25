#pragma once
#include <string>
#include <map>
#include <functional>
#include <QtCore/qstring.h>
#include <QtCore/qlist.h>
#include <QtCore/qatomic.h>
#include <QtCore/qbytearray.h>
#include <QtCore/qpointer.h>

// Forward declarations — full definitions in DzScriptServerPane.h
class AuthenticationService;
class RateLimiterService;
class IPWhitelistService;
class MetricsCollector;
class DzScriptServerPane;

// ─── HTTP Context ─────────────────────────────────────────────────────────────
// Adapter between httplib request/response and handler/middleware.
// Built from httplib::Request in setupRoutes(); response fields written back.
struct HttpContext {
    std::string body;
    std::string remoteAddr;
    std::string urlMatch;    // first regex capture group from the URL pattern
    std::string correlationId; // resolved X-Correlation-Id (job routes only; see runJobRoute)
    std::map<std::string, std::string> headers;
    std::map<std::string, std::string> queryParams;
    std::map<std::string, std::string> responseHeaders;

    // True once the client has closed its connection (httplib's
    // Request::is_connection_closed). Empty when not backed by a socket.
    std::function<bool()> isClientGone;

    int         responseStatus;
    std::string responseBody;
    std::string responseContentType;

    HttpContext() : responseStatus(200), responseContentType("application/json") {}

    std::string getHeader(const std::string& name) const {
        std::map<std::string, std::string>::const_iterator it = headers.find(name);
        return it != headers.end() ? it->second : std::string();
    }
    bool hasParam(const std::string& name) const {
        return queryParams.count(name) > 0;
    }
    std::string getParam(const std::string& name) const {
        std::map<std::string, std::string>::const_iterator it = queryParams.find(name);
        return it != queryParams.end() ? it->second : std::string();
    }
    void respond(int status, const std::string& body) {
        responseStatus = status;
        responseBody   = body;
    }
    void setHeader(const std::string& name, const std::string& value) {
        responseHeaders[name] = value;
    }
};

// ─── Middleware Interface ─────────────────────────────────────────────────────
// Returning false stops the chain and signals that a response has been set.
class IMiddleware {
public:
    virtual ~IMiddleware() {}
    virtual bool process(HttpContext& ctx) = 0;
};

// ─── Request Handler Interface ────────────────────────────────────────────────
class IRequestHandler {
public:
    virtual ~IRequestHandler() {}
    virtual void handle(HttpContext& ctx) = 0;
};

// ─── Middleware Chain ─────────────────────────────────────────────────────────
class DzScriptServerPane;

// WORKER THREAD. Runs a companion plugin's route slot on the main thread
// through the shared bounded crossing (busy check, queue timeout, receiver
// checked on the main thread) and answers ctx. Defined in RequestHandlers.cpp.
void callPluginRouteOnMainThread(DzScriptServerPane* pane, HttpContext& ctx, int queueTimeoutSec,
                                 const QPointer<QObject>& receiver, const QByteArray& slot,
                                 const QByteArray& body, const QByteArray& ip);

class MiddlewareChain {
public:
    ~MiddlewareChain();
    MiddlewareChain& add(IMiddleware* m);   // takes ownership
    bool run(HttpContext& ctx) const;       // false if any step stopped the chain
private:
    QList<IMiddleware*> m_chain;
};

// ─── Concrete Middleware ──────────────────────────────────────────────────────

class IPWhitelistMiddleware : public IMiddleware {
public:
    IPWhitelistMiddleware(IPWhitelistService& whitelist, DzScriptServerPane* pane);
    bool process(HttpContext& ctx) override;
private:
    IPWhitelistService& m_whitelist;
    DzScriptServerPane* m_pPane;
};

class RateLimitMiddleware : public IMiddleware {
public:
    RateLimitMiddleware(RateLimiterService& limiter, DzScriptServerPane* pane);
    bool process(HttpContext& ctx) override;
private:
    RateLimiterService& m_limiter;
    DzScriptServerPane* m_pPane;
};

class BodySizeMiddleware : public IMiddleware {
public:
    explicit BodySizeMiddleware(const int& maxSizeMB);
    bool process(HttpContext& ctx) override;
private:
    const int& m_maxSizeMB;
};

class AuthMiddleware : public IMiddleware {
public:
    AuthMiddleware(AuthenticationService& auth, MetricsCollector& metrics,
                   DzScriptServerPane* pane);
    bool process(HttpContext& ctx) override;
private:
    AuthenticationService& m_auth;
    MetricsCollector&      m_metrics;
    DzScriptServerPane*    m_pPane;
};

// ─── Concrete Handlers ────────────────────────────────────────────────────────

class StatusHandler : public IRequestHandler {
public:
    StatusHandler(const std::string& version, DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    std::string         m_version;
    DzScriptServerPane* m_pPane;
};

class HealthHandler : public IRequestHandler {
public:
    explicit HealthHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class MetricsHandler : public IRequestHandler {
public:
    explicit MetricsHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

// GET /capabilities. Builds the document on the main thread (render engines are
// read live); while the main thread is busy, serves the last snapshot instead.
class CapabilitiesHandler : public IRequestHandler {
public:
    explicit CapabilitiesHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class ExecuteScriptHandler : public IRequestHandler {
public:
    // queueTimeoutSec: how long a request may wait for the main thread to
    // *start* it before giving up with 503 STUDIO_BUSY (daz-script-server-3w3y).
    ExecuteScriptHandler(DzScriptServerPane* pane, int queueTimeoutSec);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
    int                 m_queueTimeoutSec;
};

class ScriptRegisterHandler : public IRequestHandler {
public:
    explicit ScriptRegisterHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class ScriptListHandler : public IRequestHandler {
public:
    explicit ScriptListHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class ScriptDeleteHandler : public IRequestHandler {
public:
    explicit ScriptDeleteHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class ScriptExecuteHandler : public IRequestHandler {
public:
    // queueTimeoutSec: how long a request may wait for the main thread to
    // *start* it before giving up with 503 STUDIO_BUSY (daz-script-server-3w3y).
    ScriptExecuteHandler(DzScriptServerPane* pane, int queueTimeoutSec);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
    int                 m_queueTimeoutSec;
};

class AsyncExecuteHandler : public IRequestHandler {
public:
    AsyncExecuteHandler(DzScriptServerPane* pane, int maxScriptLengthKB);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
    const int           m_maxScriptLengthKB;
};

class AsyncScriptHandler : public IRequestHandler {
public:
    explicit AsyncScriptHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class AsyncStatusHandler : public IRequestHandler {
public:
    explicit AsyncStatusHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class AsyncResultHandler : public IRequestHandler {
public:
    explicit AsyncResultHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class AsyncCancelHandler : public IRequestHandler {
public:
    explicit AsyncCancelHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class AsyncListHandler : public IRequestHandler {
public:
    explicit AsyncListHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class RenderHandler : public IRequestHandler {
public:
    explicit RenderHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class RenderBatchHandler : public IRequestHandler {
public:
    explicit RenderBatchHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class RenderAnimationHandler : public IRequestHandler {
public:
    explicit RenderAnimationHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class RenderCancelHandler : public IRequestHandler {
public:
    explicit RenderCancelHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class SaveCopyHandler : public IRequestHandler {
public:
    explicit SaveCopyHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};
