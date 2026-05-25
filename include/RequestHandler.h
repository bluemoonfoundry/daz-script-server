#pragma once
#include <string>
#include <map>
#include <QtCore/qstring.h>
#include <QtCore/qlist.h>
#include <QtCore/qatomic.h>

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
    std::map<std::string, std::string> headers;
    std::map<std::string, std::string> queryParams;

    int         responseStatus;
    std::string responseBody;

    HttpContext() : responseStatus(200) {}

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
    explicit StatusHandler(const std::string& version);
    void handle(HttpContext& ctx) override;
private:
    std::string m_version;
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

class ExecuteScriptHandler : public IRequestHandler {
public:
    explicit ExecuteScriptHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
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
    explicit ScriptExecuteHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
};

class AsyncExecuteHandler : public IRequestHandler {
public:
    explicit AsyncExecuteHandler(DzScriptServerPane* pane);
    void handle(HttpContext& ctx) override;
private:
    DzScriptServerPane* m_pPane;
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
