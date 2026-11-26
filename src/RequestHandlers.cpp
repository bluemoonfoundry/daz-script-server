#include "DzScriptServerPane.h"
#include "JsonStd.h"
#include "RequestHandler.h"
#include "ErrorResponse.h"
#include "MainThreadCall.h"
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
// Used by callOnMainThread() (and by handlers that must check before other
// work). Returns true, having written the 503, if the main thread is busy.
static bool respondIfMainThreadBusy(DzScriptServerPane* pane, HttpContext& ctx)
{
    if (!pane->isMainThreadBusy()) return false;
    ctx.respond(503, ErrorResponse::build(ErrorCode::STUDIO_BUSY, pane->mainThreadBusyMessage()));
    ctx.setHeader("Retry-After", ServerConfig::RETRY_AFTER_BUSY_SEC);
    return true;
}

// ─── Main-thread crossing (daz-script-server-3w3y, yau7.2.1) ─────────────────
// See MainThreadCall.h. Never use Qt::BlockingQueuedConnection from a worker:
// it has no timeout, so a stuck main thread pins every queued request's
// ActiveRequestSlot, and a failed invoke leaves the result unset.
void callOnMainThread(DzScriptServerPane* pane, HttpContext& ctx, int queueTimeoutSec,
                      const MainThreadCall::FunctionCall::Fn& fn, bool checkBusy)
{
    if (checkBusy && respondIfMainThreadBusy(pane, ctx)) return;
    HttpResult result;
    switch (MainThreadCall::post(pane, new MainThreadCall::FunctionCall(fn),
                                 queueTimeoutSec * 1000, ctx.isClientGone, &result)) {
    case MainThreadCall::Completed:
        if (result.first < 100 || result.first > 599) {
            ctx.respond(500, ErrorResponse::build(ErrorCode::INTERNAL_ERROR,
                "main-thread handler returned an invalid HTTP status"));
            return;
        }
        ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
        return;
    case MainThreadCall::GaveUp:
        ctx.respond(503, ErrorResponse::build(ErrorCode::STUDIO_BUSY,
            "DAZ Studio's main thread did not start this request within "
            + std::to_string(queueTimeoutSec) + " s (another script is still running); it was not run"));
        ctx.setHeader("Retry-After", ServerConfig::RETRY_AFTER_BUSY_SEC);
        return;
    case MainThreadCall::PostFailed:
        ctx.respond(500, ErrorResponse::build(ErrorCode::INTERNAL_ERROR, "could not reach the main thread"));
        return;
    }
}

static QByteArray toBytes(const std::string& s) { return QByteArray(s.c_str(), (int)s.size()); }

void callPluginRouteOnMainThread(DzScriptServerPane* pane, HttpContext& ctx, int queueTimeoutSec,
                                 const QPointer<QObject>& receiver, const QByteArray& slot,
                                 const QByteArray& body, const QByteArray& ip)
{
    callOnMainThread(pane, ctx, queueTimeoutSec, [receiver, slot, body, ip](DzScriptServerPane*) {
        // Read the QPointer here, on the receiver's thread: on a worker the
        // object could be deleted between the check and the call.
        if (!receiver) {
            const std::string err = ErrorResponse::build(ErrorCode::SERVER_UNAVAILABLE, "plugin handler unloaded");
            return HttpResult(503, toBytes(err));
        }
        HttpResult result(0, QByteArray());
        const bool invoked = QMetaObject::invokeMethod(receiver.data(), slot.constData(),
            Qt::DirectConnection, Q_RETURN_ARG(HttpResult, result),
            Q_ARG(QByteArray, body), Q_ARG(QByteArray, ip));
        if (!invoked) {
            const std::string err = ErrorResponse::build(ErrorCode::INTERNAL_ERROR,
                "companion plugin handler could not be called");
            return HttpResult(500, toBytes(err));
        }
        if (result.first < 100 || result.first > 599) {
            const std::string err = ErrorResponse::build(ErrorCode::INTERNAL_ERROR,
                "companion plugin handler returned an invalid HTTP status");
            return HttpResult(500, toBytes(err));
        }
        return result;
    });
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
    size_t maxSize = ServerConfig::mbToBytes(m_maxSizeMB);
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

StatusHandler::StatusHandler(const std::string& version, DzScriptServerPane* pane)
    : m_version(version), m_pPane(pane) {}

void StatusHandler::handle(HttpContext& ctx)
{
    const QByteArray instanceId = m_pPane->serverInstanceId();
    ctx.responseBody = "{\"running\":true,\"version\":\"" + m_version + "\"";
    ctx.responseBody += ",\"server_instance_id\":\"";
    ctx.responseBody.append(instanceId.constData(), instanceId.size());
    ctx.responseBody += "\",\"scene_revision\":" + std::to_string(m_pPane->sceneRevision()) + "}";
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

CapabilitiesHandler::CapabilitiesHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void CapabilitiesHandler::handle(HttpContext& ctx)
{
    if (m_pPane->isMainThreadBusy()) {
        // Discovery should not fail just because a render is running: serve the
        // last document built on the main thread (render_engines.source = "snapshot").
        QByteArray snapshot = m_pPane->capabilitiesSnapshot();
        if (!snapshot.isEmpty()) {
            ctx.respond(200, std::string(snapshot.constData(), snapshot.size()));
            return;
        }
    }
    callOnMainThread(m_pPane, ctx, m_pPane->mainThreadQueueTimeoutSec(), [](DzScriptServerPane* pane) {
        return pane->handleCapabilitiesRequest();
    });
}

// ─────────────────────────────────────────────────────────────────────────────

ExecuteScriptHandler::ExecuteScriptHandler(DzScriptServerPane* pane, int queueTimeoutSec)
    : m_pPane(pane), m_queueTimeoutSec(queueTimeoutSec) {}

void ExecuteScriptHandler::handle(HttpContext& ctx)
{
    const qint64 acceptedAtMs = QDateTime::currentMSecsSinceEpoch();
    const QByteArray body = toBytes(ctx.body), ip = toBytes(ctx.remoteAddr);
    callOnMainThread(m_pPane, ctx, m_queueTimeoutSec, [body, ip, acceptedAtMs](DzScriptServerPane* pane) {
        return pane->handleExecuteRequest(body, ip, acceptedAtMs);
    });
}

// ─────────────────────────────────────────────────────────────────────────────

ScriptRegisterHandler::ScriptRegisterHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void ScriptRegisterHandler::handle(HttpContext& ctx)
{
    const QByteArray body = toBytes(ctx.body), ip = toBytes(ctx.remoteAddr);
    callOnMainThread(m_pPane, ctx, m_pPane->mainThreadQueueTimeoutSec(), [body, ip](DzScriptServerPane* pane) {
        return pane->handleRegisterScript(body, ip);
    });
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

ScriptExecuteHandler::ScriptExecuteHandler(DzScriptServerPane* pane, int queueTimeoutSec)
    : m_pPane(pane), m_queueTimeoutSec(queueTimeoutSec) {}

void ScriptExecuteHandler::handle(HttpContext& ctx)
{
    if (respondIfMainThreadBusy(m_pPane, ctx)) return;
    std::string scriptText;
    if (!m_pPane->lookupRegistryScript(ctx.urlMatch, scriptText)) {
        ctx.respond(404, ErrorResponse::build(ErrorCode::SCRIPT_NOT_FOUND, ctx.urlMatch));
        return;
    }

    const QByteArray script = toBytes(scriptText), scriptId = toBytes(ctx.urlMatch);
    const QByteArray body = toBytes(ctx.body), ip = toBytes(ctx.remoteAddr);
    callOnMainThread(m_pPane, ctx, m_queueTimeoutSec, [script, scriptId, body, ip](DzScriptServerPane* pane) {
        return pane->handleRegistryExecuteRequest(script, scriptId, body, ip);
    }, /*checkBusy=*/false);
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncExecuteHandler::AsyncExecuteHandler(DzScriptServerPane* pane, int maxScriptLengthKB)
    : m_pPane(pane), m_maxScriptLengthKB(maxScriptLengthKB) {}

void AsyncExecuteHandler::handle(HttpContext& ctx)
{
    QByteArray bodyBytes(ctx.body.c_str(), (int)ctx.body.size());
    QByteArray corrBytes(ctx.correlationId.c_str(), (int)ctx.correlationId.size());
#if DAZ_SDK_MAJOR_VERSION >= 6
    // Enqueue is deliberately worker-thread-safe. Sending this through a
    // BlockingQueuedConnection makes an "async" submit wait behind the very
    // main-thread job it is meant to queue after, which also makes queued
    // cancellation impossible while Daz is busy.
    QByteArray clientIPBytes(ctx.remoteAddr.c_str(), (int)ctx.remoteAddr.size());
    HttpResult result = m_pPane->handleAsyncExecuteEnqueue(
        bodyBytes, clientIPBytes, m_maxScriptLengthKB, corrBytes);
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
#else
    // Qt 4's JsonStd parser uses QScriptEngine, so Studio 4 must retain the
    // main-thread crossing even though Studio 6 can enqueue directly.
    const QByteArray clientIPBytes = toBytes(ctx.remoteAddr);
    const int maxKB = m_maxScriptLengthKB;
    callOnMainThread(m_pPane, ctx, m_pPane->mainThreadQueueTimeoutSec(),
        [bodyBytes, clientIPBytes, maxKB, corrBytes](DzScriptServerPane* pane) {
            return pane->handleAsyncExecuteEnqueue(bodyBytes, clientIPBytes, maxKB, corrBytes);
        });
#endif
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
    QByteArray corrBytes(ctx.correlationId.c_str(), (int)ctx.correlationId.size());
#if DAZ_SDK_MAJOR_VERSION >= 6
    HttpResult result = m_pPane->handleAsyncScriptEnqueue(
        scriptBytes, scriptIdBytes, bodyBytes, corrBytes);
    ctx.respond(result.first, std::string(result.second.constData(), result.second.size()));
#else
    callOnMainThread(m_pPane, ctx, m_pPane->mainThreadQueueTimeoutSec(),
        [scriptBytes, scriptIdBytes, bodyBytes, corrBytes](DzScriptServerPane* pane) {
            return pane->handleAsyncScriptEnqueue(scriptBytes, scriptIdBytes, bodyBytes, corrBytes);
        });
#endif
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
    std::pair<int, std::string> result = m_pPane->getAsyncResultJson(ctx.urlMatch, doWait, timeoutSec, ctx.isClientGone);
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
    const QByteArray bodyBytes = toBytes(ctx.body), corrBytes = toBytes(ctx.correlationId);
    callOnMainThread(m_pPane, ctx, m_pPane->mainThreadQueueTimeoutSec(), [bodyBytes, corrBytes](DzScriptServerPane* pane) {
        return pane->handleAsyncRenderEnqueue(bodyBytes, corrBytes);
    });
}

RenderBatchHandler::RenderBatchHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void RenderBatchHandler::handle(HttpContext& ctx)
{
    const QByteArray bodyBytes = toBytes(ctx.body), corrBytes = toBytes(ctx.correlationId);
    callOnMainThread(m_pPane, ctx, m_pPane->mainThreadQueueTimeoutSec(), [bodyBytes, corrBytes](DzScriptServerPane* pane) {
        return pane->handleAsyncRenderBatchEnqueue(bodyBytes, corrBytes);
    });
}

RenderAnimationHandler::RenderAnimationHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void RenderAnimationHandler::handle(HttpContext& ctx)
{
    const QByteArray bodyBytes = toBytes(ctx.body), corrBytes = toBytes(ctx.correlationId);
    callOnMainThread(m_pPane, ctx, m_pPane->mainThreadQueueTimeoutSec(), [bodyBytes, corrBytes](DzScriptServerPane* pane) {
        return pane->handleAsyncRenderAnimationEnqueue(bodyBytes, corrBytes);
    });
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
    const QByteArray bodyBytes = toBytes(ctx.body);
    callOnMainThread(m_pPane, ctx, m_pPane->mainThreadQueueTimeoutSec(), [bodyBytes](DzScriptServerPane* pane) {
        return pane->handleSaveCopy(bodyBytes);
    });
}
