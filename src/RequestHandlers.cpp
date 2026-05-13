#include "DzScriptServerPane.h"
#include "RequestHandler.h"
#include "JsonBuilder.h"
#include "ErrorResponse.h"
#include "RequestValidator.h"

#include <QtCore/qdatetime.h>
#include <QtCore/qmetaobject.h>
#include <QtCore/qpair.h>
#include <QtScript/qscriptengine.h>
#include <QtScript/qscriptvalue.h>

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
    QString ip = QString::fromStdString(ctx.remoteAddr);
    if (m_whitelist.isAllowed(ip)) return true;

    ctx.respond(403, ErrorResponse::build(ErrorCode::IP_NOT_WHITELISTED, ctx.remoteAddr));

    QString logMsg = QString("[%1] [BLOCKED] %2 - IP not whitelisted")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss")).arg(ip);
    QMetaObject::invokeMethod(m_pPane, "appendLog", Qt::QueuedConnection,
        Q_ARG(QString, logMsg));
    return false;
}

// ─────────────────────────────────────────────────────────────────────────────

RateLimitMiddleware::RateLimitMiddleware(RateLimiterService& limiter, DzScriptServerPane* pane)
    : m_limiter(limiter), m_pPane(pane) {}

bool RateLimitMiddleware::process(HttpContext& ctx)
{
    QString ip = QString::fromStdString(ctx.remoteAddr);
    if (m_limiter.checkRequest(ip)) return true;

    ctx.respond(429, ErrorResponse::build(ErrorCode::RATE_LIMIT_EXCEEDED, ctx.remoteAddr));

    QString logMsg = QString("[%1] [RATE LIMIT] %2")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss")).arg(ip);
    QMetaObject::invokeMethod(m_pPane, "appendLog", Qt::QueuedConnection,
        Q_ARG(QString, logMsg));
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

    QString ip = QString::fromStdString(ctx.remoteAddr);
    QString logMsg = QString("[%1] [AUTH FAILED] %2")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss")).arg(ip);
    QMetaObject::invokeMethod(m_pPane, "appendLog", Qt::QueuedConnection,
        Q_ARG(QString, logMsg));
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
    ctx.responseBody = m_pPane->getHealthJson().toStdString();
}

// ─────────────────────────────────────────────────────────────────────────────

MetricsHandler::MetricsHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void MetricsHandler::handle(HttpContext& ctx)
{
    ctx.responseBody = m_pPane->getMetricsJson().toStdString();
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
    ctx.responseBody = m_pPane->listScriptsJson().toStdString();
}

// ─────────────────────────────────────────────────────────────────────────────

ScriptDeleteHandler::ScriptDeleteHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void ScriptDeleteHandler::handle(HttpContext& ctx)
{
    QString id = QString::fromStdString(ctx.urlMatch);
    QString ip = QString::fromStdString(ctx.remoteAddr);
    QPair<int, QString> result = m_pPane->deleteRegistryScriptJson(id, ip);
    ctx.respond(result.first, result.second.toStdString());
}

// ─────────────────────────────────────────────────────────────────────────────

ScriptExecuteHandler::ScriptExecuteHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void ScriptExecuteHandler::handle(HttpContext& ctx)
{
    QString id = QString::fromStdString(ctx.urlMatch);
    QString scriptText;
    if (!m_pPane->lookupRegistryScript(id, scriptText)) {
        ctx.respond(404, ErrorResponse::build(ErrorCode::SCRIPT_NOT_FOUND, id.toStdString()));
        return;
    }

    QByteArray scriptBytes   = scriptText.toUtf8();
    QByteArray scriptIdBytes = id.toUtf8();
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
    QScriptEngine parseEngine;
    QScriptValue  parsed = parseEngine.evaluate(
        "(" + QString::fromUtf8(ctx.body.c_str(), (int)ctx.body.size()) + ")");
    if (parseEngine.hasUncaughtException()) {
        ctx.respond(400, ErrorResponse::build(ErrorCode::INVALID_JSON));
        return;
    }
    QVariantMap body       = parsed.toVariant().toMap();
    QString     scriptText = body.value("script").toString();

    ValidationResult vr = RequestValidator::validateRequiredField(scriptText, "script");
    if (!vr.valid) {
        ctx.respond(vr.httpStatus(), vr.toErrorJson());
        return;
    }

    qint64  submittedAt  = 0;
    QString enqueueError;
    QString requestId = m_pPane->enqueueAsyncRequest(
        scriptText, body.value("args").toMap(), "execute", submittedAt, enqueueError);

    if (requestId.isEmpty()) {
        ctx.respond(503, ErrorResponse::build(ErrorCode::SERVER_UNAVAILABLE,
            enqueueError.toStdString()));
        return;
    }

    JsonBuilder json;
    json.startObject();
    json.addMember("request_id",   requestId);
    json.addMember("status",       "queued");
    json.addMember("submitted_at",
        QDateTime::fromMSecsSinceEpoch(submittedAt).toString(Qt::ISODate));
    json.finishObject();
    ctx.responseBody = json.toString().toStdString();
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncScriptHandler::AsyncScriptHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncScriptHandler::handle(HttpContext& ctx)
{
    QString id = QString::fromStdString(ctx.urlMatch);
    QString scriptText;
    if (!m_pPane->lookupRegistryScript(id, scriptText)) {
        ctx.respond(404, ErrorResponse::build(ErrorCode::SCRIPT_NOT_FOUND, id.toStdString()));
        return;
    }

    QVariantMap argsMap;
    if (!ctx.body.empty()) {
        QScriptEngine parseEngine;
        QScriptValue  parsed = parseEngine.evaluate(
            "(" + QString::fromUtf8(ctx.body.c_str(), (int)ctx.body.size()) + ")");
        if (!parseEngine.hasUncaughtException())
            argsMap = parsed.toVariant().toMap().value("args").toMap();
    }

    qint64  submittedAt  = 0;
    QString enqueueError;
    QString requestId = m_pPane->enqueueAsyncRequest(scriptText, argsMap, "script", submittedAt,
                                                     enqueueError);

    if (requestId.isEmpty()) {
        ctx.respond(503, ErrorResponse::build(ErrorCode::SERVER_UNAVAILABLE,
            enqueueError.toStdString()));
        return;
    }

    JsonBuilder json;
    json.startObject();
    json.addMember("request_id",   requestId);
    json.addMember("status",       "queued");
    json.addMember("submitted_at",
        QDateTime::fromMSecsSinceEpoch(submittedAt).toString(Qt::ISODate));
    json.finishObject();
    ctx.responseBody = json.toString().toStdString();

    QString logMsg = QString("[%1] [%2] [ASYNC QUEUED] script:%3 -> %4")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
        .arg(QString::fromStdString(ctx.remoteAddr))
        .arg(id).arg(requestId);
    QMetaObject::invokeMethod(m_pPane, "appendLog", Qt::QueuedConnection,
        Q_ARG(QString, logMsg));
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncStatusHandler::AsyncStatusHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncStatusHandler::handle(HttpContext& ctx)
{
    QPair<int, QString> result =
        m_pPane->getAsyncStatusJson(QString::fromStdString(ctx.urlMatch));
    ctx.respond(result.first, result.second.toStdString());
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncResultHandler::AsyncResultHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncResultHandler::handle(HttpContext& ctx)
{
    bool doWait = ctx.hasParam("wait") && ctx.getParam("wait") == "true";
    int  timeoutSec = 300;
    if (ctx.hasParam("timeout")) {
        bool ok = false;
        int t = QString::fromStdString(ctx.getParam("timeout")).toInt(&ok);
        if (ok && t > 0) timeoutSec = t;
    }
    QPair<int, QString> result = m_pPane->getAsyncResultJson(
        QString::fromStdString(ctx.urlMatch), doWait, timeoutSec);
    ctx.respond(result.first, result.second.toStdString());
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncCancelHandler::AsyncCancelHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncCancelHandler::handle(HttpContext& ctx)
{
    QPair<int, QString> result = m_pPane->cancelAsyncRequestJson(
        QString::fromStdString(ctx.urlMatch),
        QString::fromStdString(ctx.remoteAddr));
    ctx.respond(result.first, result.second.toStdString());
}

// ─────────────────────────────────────────────────────────────────────────────

AsyncListHandler::AsyncListHandler(DzScriptServerPane* pane) : m_pPane(pane) {}

void AsyncListHandler::handle(HttpContext& ctx)
{
    QString filter = ctx.hasParam("status")
        ? QString::fromStdString(ctx.getParam("status"))
        : QString();
    ctx.responseBody = m_pPane->listAsyncRequestsJson(filter).toStdString();
}
