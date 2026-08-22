#include "DzScriptServerPane.h"
#include "JsonStd.h"
#include "RequestHandler.h"
#include "ErrorResponse.h"
#include <QtCore/qmetaobject.h>
#include <QtCore/qdatetime.h>

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

// ─── Shared busy-check helper ──────────────────────────────────────────────────
// Called first by every handler that would otherwise block on
// Qt::BlockingQueuedConnection with no timeout. Returns true (and has
// already written the 503 response) if the main thread is currently busy.
static bool respondIfMainThreadBusy(DzScriptServerPane* pane, HttpContext& ctx)
{
    if (!pane->isMainThreadBusy()) return false;
    ctx.respond(503, ErrorResponse::build(ErrorCode::STUDIO_BUSY, pane->mainThreadBusyMessage()));
    ctx.setHeader("Retry-After", "2");
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
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    qint64 acceptedAtMs = QDateTime::currentMSecsSinceEpoch();
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    QByteArray ipBytes(ctx.remoteAddr.c_str(), (int)ctx.remoteAddr.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleExecuteRequest",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes),
        Q_ARG(QByteArray, ipBytes),
        Q_ARG(qint64, acceptedAtMs));
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
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
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

AsyncExecuteHandler::AsyncExecuteHandler(DzScriptServerPane* pane, int maxScriptLengthKB)
    : m_pPane(pane), m_maxScriptLengthKB(maxScriptLengthKB) {}

void AsyncExecuteHandler::handle(HttpContext& ctx)
{
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
#if DAZ_SDK_MAJOR_VERSION >= 6
    // Enqueue is deliberately worker-thread-safe. Sending this through a
    // BlockingQueuedConnection makes an "async" submit wait behind the very
    // main-thread job it is meant to queue after, which also makes queued
    // cancellation impossible while Daz is busy.
    QByteArray clientIPBytes(ctx.remoteAddr.c_str(), (int)ctx.remoteAddr.size());
    HttpResult result = m_pPane->handleAsyncExecuteEnqueue(
        bodyBytes, clientIPBytes, m_maxScriptLengthKB);
#else
    // Qt 4's JsonStd parser uses QScriptEngine, so Studio 4 must retain the
    // main-thread crossing even though Studio 6 can enqueue directly.
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    QByteArray clientIPBytes(ctx.remoteAddr.c_str(), (int)ctx.remoteAddr.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleAsyncExecuteEnqueue",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes),
        Q_ARG(QByteArray, clientIPBytes),
        Q_ARG(int, m_maxScriptLengthKB));
#endif
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
#if DAZ_SDK_MAJOR_VERSION >= 6
    HttpResult result = m_pPane->handleAsyncScriptEnqueue(
        scriptBytes, scriptIdBytes, bodyBytes);
#else
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleAsyncScriptEnqueue",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, scriptBytes),
        Q_ARG(QByteArray, scriptIdBytes),
        Q_ARG(QByteArray, bodyBytes));
#endif
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

// ─────────────────────────────────────────────────────────────────────────────

RenderHandler::RenderHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void RenderHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleAsyncRenderEnqueue",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}

RenderBatchHandler::RenderBatchHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void RenderBatchHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleAsyncRenderBatchEnqueue",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}

RenderAnimationHandler::RenderAnimationHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void RenderAnimationHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleAsyncRenderAnimationEnqueue",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}

// ─────────────────────────────────────────────────────────────────────────────

RenderCancelHandler::RenderCancelHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void RenderCancelHandler::handle(HttpContext& ctx)
{
    std::pair<int, std::string> result = m_pPane->cancelRenderRequestJson(ctx.urlMatch, ctx.remoteAddr);
    ctx.respond(result.first, result.second);
}

// ─────────────────────────────────────────────────────────────────────────────

SaveCopyHandler::SaveCopyHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void SaveCopyHandler::handle(HttpContext& ctx)
{
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    HttpResult result;
    QMetaObject::invokeMethod(m_pPane, "handleSaveCopy",
        Qt::BlockingQueuedConnection,
        Q_RETURN_ARG(HttpResult, result),
        Q_ARG(QByteArray, bodyBytes));
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
}
