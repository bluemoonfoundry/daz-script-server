#include "DzScriptServerPane.h"
#include "JsonStd.h"
#include "RequestHandler.h"
#include "ErrorResponse.h"
#include <QtCore/qmetaobject.h>

// ─── MiddlewareChain ──────────────────────────────────────────────────────────

MiddlewareChain::~MiddlewareChain()
{
    for (int i = 0; i < m_chain.size(); ++i)
        delete m_chain[i];
}

MiddlewareChain& MiddlewareChain::add(IMiddleware* m)
{
    m_chain.append(m);
    return *this;
}

bool MiddlewareChain::run(HttpContext& ctx) const
{
    for (int i = 0; i < m_chain.size(); ++i) {
        if (!m_chain[i]->process(ctx))
            return false;
    }
    return true;
}

// ─── Concrete Middleware ──────────────────────────────────────────────────────

IPWhitelistMiddleware::IPWhitelistMiddleware(IPWhitelistService& whitelist, DzScriptServerPane* pane)
    : m_whitelist(whitelist), m_pPane(pane) {}

bool IPWhitelistMiddleware::process(HttpContext& ctx)
{
    if (m_whitelist.isAllowed(ctx.remoteAddr)) return true;

    ctx.respond(403, ErrorResponse::build(ErrorCode::IP_NOT_WHITELISTED, ctx.remoteAddr));

    std::string logLine = "[" + JsonStd::currentTime() + "] [BLOCKED] " + ctx.remoteAddr + " - IP not whitelisted";
    QMetaObject::invokeMethod(m_pPane, "appendLogBytes", Qt::QueuedConnection,
        Q_ARG(QByteArray, QByteArray(logLine.c_str(), (int)logLine.size())));
    return false;
}

// ─────────────────────────────────────────────────────────────────────────────

RateLimitMiddleware::RateLimitMiddleware(RateLimiterService& limiter, DzScriptServerPane* pane)
    : m_limiter(limiter), m_pPane(pane) {}

bool RateLimitMiddleware::process(HttpContext& ctx)
{
    if (m_limiter.checkRequest(ctx.remoteAddr)) return true;

    ctx.respond(429, ErrorResponse::build(ErrorCode::RATE_LIMIT_EXCEEDED, ctx.remoteAddr));

    std::string logLine = "[" + JsonStd::currentTime() + "] [RATE LIMIT] " + ctx.remoteAddr;
    QMetaObject::invokeMethod(m_pPane, "appendLogBytes", Qt::QueuedConnection,
        Q_ARG(QByteArray, QByteArray(logLine.c_str(), (int)logLine.size())));
    return false;
}

// ─────────────────────────────────────────────────────────────────────────────

BodySizeMiddleware::BodySizeMiddleware(const int& maxSizeMB)
    : m_maxSizeMB(maxSizeMB) {}

bool BodySizeMiddleware::process(HttpContext& ctx)
{
    size_t maxSize = static_cast<size_t>(m_maxSizeMB) * 1024 * 1024;
    if (ctx.body.size() <= maxSize) return true;

    std::string detail =
        "Body is " + std::to_string(ctx.body.size()) +
        " bytes; maximum is " + std::to_string(m_maxSizeMB) +
        " MB (" + std::to_string(maxSize) + " bytes)";
    ctx.respond(413, ErrorResponse::build(ErrorCode::BODY_TOO_LARGE, detail));
    return false;
}

// ─────────────────────────────────────────────────────────────────────────────

AuthMiddleware::AuthMiddleware(AuthenticationService& auth, MetricsCollector& metrics,
                               DzScriptServerPane* pane)
    : m_auth(auth), m_metrics(metrics), m_pPane(pane) {}

bool AuthMiddleware::process(HttpContext& ctx)
{
    if (!m_auth.isEnabled()) return true;

    std::string token = ctx.getHeader("x-api-token");
    if (token.empty()) {
        std::string auth = ctx.getHeader("authorization");
        if (auth.find("Bearer ") == 0) token = auth.substr(7);
    }
    if (m_auth.validateToken(token)) return true;

    ErrorCode code = token.empty() ? ErrorCode::AUTH_MISSING_TOKEN : ErrorCode::AUTH_INVALID_TOKEN;
    ctx.respond(401, ErrorResponse::build(code));
    m_metrics.recordAuthFailure();

    std::string logLine = "[" + JsonStd::currentTime() + "] [AUTH FAILED] " + ctx.remoteAddr;
    QMetaObject::invokeMethod(m_pPane, "appendLogBytes", Qt::QueuedConnection,
        Q_ARG(QByteArray, QByteArray(logLine.c_str(), (int)logLine.size())));
    return false;
}

// ─── Concrete Handlers ────────────────────────────────────────────────────────

StatusHandler::StatusHandler(const std::string& version) : m_version(version) {}

void StatusHandler::handle(HttpContext& ctx)
{
    ctx.responseBody = "{\"running\":true,\"version\":\"" + m_version + "\"}";
}

// ─────────────────────────────────────────────────────────────────────────────

HealthHandler::HealthHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void HealthHandler::handle(HttpContext& ctx)
{
    ctx.responseBody = m_pPane->getHealthJson();
}

// ─────────────────────────────────────────────────────────────────────────────

MetricsHandler::MetricsHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void MetricsHandler::handle(HttpContext& ctx)
{
    ctx.responseBody = m_pPane->getMetricsJson();
}

// ─────────────────────────────────────────────────────────────────────────────

ExecuteScriptHandler::ExecuteScriptHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void ExecuteScriptHandler::handle(HttpContext& ctx)
{
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    QByteArray ipBytes(ctx.remoteAddr.c_str(), (int)ctx.remoteAddr.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleExecuteRequest",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes),
        Q_ARG(QByteArray, ipBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}

// ─────────────────────────────────────────────────────────────────────────────

ScriptRegisterHandler::ScriptRegisterHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void ScriptRegisterHandler::handle(HttpContext& ctx)
{
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    QByteArray ipBytes(ctx.remoteAddr.c_str(), (int)ctx.remoteAddr.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleRegisterScript",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes),
        Q_ARG(QByteArray, ipBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}

// ─────────────────────────────────────────────────────────────────────────────

ScriptListHandler::ScriptListHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void ScriptListHandler::handle(HttpContext& ctx)
{
    ctx.responseBody = m_pPane->listScriptsJson();
}

// ─────────────────────────────────────────────────────────────────────────────

ScriptDeleteHandler::ScriptDeleteHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void ScriptDeleteHandler::handle(HttpContext& ctx)
{
    std::pair<int, std::string> result = m_pPane->deleteRegistryScriptJson(ctx.urlMatch, ctx.remoteAddr);
    ctx.respond(result.first, result.second);
}

// ─────────────────────────────────────────────────────────────────────────────

ScriptExecuteHandler::ScriptExecuteHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void ScriptExecuteHandler::handle(HttpContext& ctx)
{
    std::string scriptText;
    if (!m_pPane->lookupRegistryScript(ctx.urlMatch, scriptText)) {
        ctx.respond(404, ErrorResponse::build(ErrorCode::SCRIPT_NOT_FOUND, ctx.urlMatch));
        return;
    }

    QByteArray scriptBytes(scriptText.c_str(), (int)scriptText.size());
    QByteArray scriptIdBytes(ctx.urlMatch.c_str(), (int)ctx.urlMatch.size());
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    QByteArray ipBytes(ctx.remoteAddr.c_str(), (int)ctx.remoteAddr.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleRegistryExecuteRequest",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, scriptBytes),
        Q_ARG(QByteArray, scriptIdBytes),
        Q_ARG(QByteArray, bodyBytes),
        Q_ARG(QByteArray, ipBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncExecuteHandler::AsyncExecuteHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncExecuteHandler::handle(HttpContext& ctx)
{
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleAsyncExecuteEnqueue",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncScriptHandler::AsyncScriptHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncScriptHandler::handle(HttpContext& ctx)
{
    std::string scriptText;
    if (!m_pPane->lookupRegistryScript(ctx.urlMatch, scriptText)) {
        ctx.respond(404, ErrorResponse::build(ErrorCode::SCRIPT_NOT_FOUND, ctx.urlMatch));
        return;
    }

    QByteArray scriptBytes(scriptText.c_str(), (int)scriptText.size());
    QByteArray scriptIdBytes(ctx.urlMatch.c_str(), (int)ctx.urlMatch.size());
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleAsyncScriptEnqueue",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, scriptBytes),
        Q_ARG(QByteArray, scriptIdBytes),
        Q_ARG(QByteArray, bodyBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncStatusHandler::AsyncStatusHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncStatusHandler::handle(HttpContext& ctx)
{
    std::pair<int, std::string> result = m_pPane->getAsyncStatusJson(ctx.urlMatch);
    ctx.respond(result.first, result.second);
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncResultHandler::AsyncResultHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncResultHandler::handle(HttpContext& ctx)
{
    bool doWait = ctx.hasParam("wait") && ctx.getParam("wait") == "true";
    int  timeoutSec = 300;
    if (ctx.hasParam("timeout")) {
        const std::string& ts = ctx.getParam("timeout");
        char* end = nullptr;
        long t = std::strtol(ts.c_str(), &end, 10);
        if (end != ts.c_str() && t > 0) timeoutSec = (int)t;
    }
    std::pair<int, std::string> result = m_pPane->getAsyncResultJson(ctx.urlMatch, doWait, timeoutSec);
    ctx.respond(result.first, result.second);
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncCancelHandler::AsyncCancelHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncCancelHandler::handle(HttpContext& ctx)
{
    std::pair<int, std::string> result = m_pPane->cancelAsyncRequestJson(ctx.urlMatch, ctx.remoteAddr);
    ctx.respond(result.first, result.second);
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncListHandler::AsyncListHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncListHandler::handle(HttpContext& ctx)
{
    std::string filter = ctx.hasParam("status") ? ctx.getParam("status") : std::string();
    ctx.responseBody = m_pPane->listAsyncRequestsJson(filter);
}
