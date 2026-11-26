// DzScriptServerPane: script execution (sync, registry, async submit) and the
// main-thread async queue drain.
#include "PaneInternal.h"

// ─── Script Registry public API (called from HTTP threads) ───────────────────

std::string DzScriptServerPane::listScriptsJson() const
{
	return m_scriptRegistry.listJson();
}

std::pair<int, std::string> DzScriptServerPane::deleteRegistryScriptJson(
    const std::string& id, const std::string& clientIP)
{
	if (!m_scriptRegistry.remove(id)) {
		return {404, ErrorResponse::build(ErrorCode::SCRIPT_NOT_FOUND, id)};
	}

	postLog("[" + clientIP + "] [REGISTRY] Deleted script: " + id);

	QVariantMap body;
	body.insert("success", true);
	body.insert("id", QString::fromUtf8(id.c_str(), (int)id.size()));
	return {200, JsonStd::variantToJson(body)};
}

bool DzScriptServerPane::lookupRegistryScript(const std::string& id, std::string& outScript) const
{
	return m_scriptRegistry.lookup(id, outScript);
}

// ─── Async Request public API (called from HTTP threads) ──────────────────────

QString DzScriptServerPane::enqueueAsyncRequest(const QString& scriptText,
                                                const QString& scriptFile,
                                                const QString& reportFile,
                                                const QVariantMap& args,
                                                const QString& idPrefix,
                                                const QString& correlationId,
                                                qint64& outSubmittedAt,
                                                QString& outError)
{
	AsyncRequestManager::SubmitResult r = m_pAsyncMgr->submit(
		scriptText, scriptFile, reportFile, args, idPrefix, correlationId);
	outSubmittedAt = r.submittedAt;
	outError       = r.error;
	if (!r.accepted) {
		postLog("[WARN] Async queue rejected: " + JsonStd::qstrToStd(r.error));
	}
	return r.id;
}

std::pair<int, std::string> DzScriptServerPane::getAsyncStatusJson(const std::string& requestId)
{
	return m_pAsyncMgr->getStatusJson(requestId);
}

std::pair<int, std::string> DzScriptServerPane::getAsyncResultJson(const std::string& requestId,
                                                                   bool doWait, int timeoutSec,
                                                                   const std::function<bool()>& isClientGone)
{
	return m_pAsyncMgr->getResultJson(requestId, doWait, timeoutSec, isClientGone);
}

// Any thread. A render cancelled before it started never reaches
// notifyStarted/notifyFailed in processNextAsyncRequest, so end its
// /render/:id/progress stream here (yau7.2.8). The broker is mutex-protected
// and stores the event for subscribers that connect later.
void DzScriptServerPane::endProgressOfCancelledRender(const QString& requestId)
{
	if (RenderProgressBroker* broker = m_pRenderProgress)
		broker->notifyFailed(requestId, ErrorCode::JOB_CANCELLED, "Cancelled before execution started", 0);
}

std::pair<int, std::string> DzScriptServerPane::cancelAsyncRequestJson(const std::string& requestId,
                                                                       const std::string& clientIP)
{
	bool cancelledQueuedRender = false;
	std::pair<int, std::string> result = m_pAsyncMgr->cancelJson(requestId, clientIP, &cancelledQueuedRender);
	if (cancelledQueuedRender)
		endProgressOfCancelledRender(QString::fromStdString(requestId));
	if (result.first == 200) {
		postLog("[ASYNC CANCEL] " + requestId);
	}
	return result;
}

std::pair<int, std::string> DzScriptServerPane::cancelRenderRequestJson(const std::string& requestId,
                                                                        const std::string& clientIP)
{
	bool cancelledQueuedRender = false;
	std::pair<int, std::string> result = m_pAsyncMgr->cancelRenderJson(requestId, clientIP, &cancelledQueuedRender);
	if (cancelledQueuedRender)
		endProgressOfCancelledRender(QString::fromStdString(requestId));
	if (result.first == 200) {
		postLog("[RENDER CANCEL] " + requestId);
	}
	return result;
}

std::string DzScriptServerPane::listAsyncRequestsJson(const std::string& statusFilter)
{
	return m_pAsyncMgr->listJson(statusFilter);
}

// ─── Main-thread request handler ──────────────────────────────────────────────

DzScriptServerPane::CapturedScriptRun DzScriptServerPane::runCapturedScript(
	const QString& scriptFile, const QString& scriptText, const QVariantMap& args)
{
	// Turns print() capture on for exactly this run; the destructor undoes it
	// even if something throws, so capture can't stay on or the signal
	// stay connected.
	struct CaptureScope {
		DzScriptServerPane* pane;
		explicit CaptureScope(DzScriptServerPane* p) : pane(p) {
			pane->m_capturedLogLines.clear();
			pane->m_bCapturingLog = true;
			connect(dzApp, DSS_DEBUG_SIGNAL, pane, SLOT(onMessagePosted(const QString&)),
			        Qt::DirectConnection);
		}
		~CaptureScope() {
			disconnect(dzApp, DSS_DEBUG_SIGNAL, pane, SLOT(onMessagePosted(const QString&)));
			pane->m_bCapturingLog = false;
		}
	} scope(this);

	CapturedScriptRun run;
	// Reuse the persistent DzScript instance instead of constructing/
	// destroying one per request — see m_pPersistentScript's declaration.
	ensurePersistentScript()->clear();
	if (!scriptFile.isEmpty()) {
		// loadFromFile sets the filename so getScriptFileName() and relative
		// include() calls work inside the script.
		if (!m_pPersistentScript->loadFromFile(scriptFile)) {
			run.loaded = false;
			run.error  = QString("Failed to load script file: %1").arg(scriptFile);
			return run;
		}
	} else {
		m_pPersistentScript->setCode(scriptText);
	}

	// Args are reachable in scripts via getArguments()[0].
	const ScriptRunResult r = runDazScript(m_pPersistentScript, args, scriptFile);
	// The busy sample is taken every PROGRESS_POLL_INTERVAL_MS, and the last
	// one may date from inside this script (a render's DzProgress). Refresh it
	// before the caller publishes the result, or a client's next request can
	// get 503 STUDIO_BUSY for a progress dialog that has already closed.
	pollProgressBusy();
	run.success = r.success;
	run.result  = r.result;
	if (!r.success)
		run.error = r.errorLine > 0 ? QString("Line %1: %2").arg(r.errorLine).arg(r.errorMessage)
		                            : r.errorMessage;
#if DAZ_SDK_MAJOR_VERSION >= 6
	run.output = r.output;               // SDK6: evaluate() bypasses the debugMsg signal
#else
	run.output = m_capturedLogLines;
#endif
	return run;
}

HttpResult DzScriptServerPane::handleExecuteRequest(const QByteArray& jsonBody, const QByteArray& clientIP, qint64 acceptedAtMs)
{
	QTime startTime = QTime::currentTime();
	qint64 dispatchedAtMs = QDateTime::currentMSecsSinceEpoch();
	m_metrics.recordMainThreadWait(dispatchedAtMs - acceptedAtMs);
	QString clientIPStr = QString::fromUtf8(clientIP.constData(), clientIP.size());
	QString requestId = MetricsCollector::generateRequestId();

	// Parse JSON body
	QVariantMap bodyMap;
	std::string parseErrDetail;
	if (!JsonStd::parseObject(jsonBody, bodyMap, parseErrDetail)) {
		appendLog(QString("[%1] [%2] [ERR] [0ms] [%3] JSON parse error")
			.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
			.arg(clientIPStr).arg(requestId));
		m_metrics.recordRequest(false);
		return HttpResult(400,
			stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON, parseErrDetail)));
	}

	QString scriptFile   = bodyMap.value("scriptFile").toString();
	QString scriptText   = bodyMap.value("script").toString();
	QVariantMap argsMap  = bodyMap.value("args").toMap();

	// Warn if both fields are provided (scriptFile takes precedence)
	if (!scriptFile.isEmpty() && !scriptText.isEmpty()) {
		appendLog(QString("[%1] [%2] [WARN] [%3] Both scriptFile and script provided; using scriptFile")
			.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
			.arg(clientIPStr).arg(requestId));
	}

	// Centralised input validation
	ValidationResult vr = RequestValidator::validateExecuteFields(scriptFile, scriptText, m_nMaxScriptLengthKB);
	if (!vr.valid) {
		appendLog(QString("[%1] [%2] [ERR] [0ms] [%3] Validation: %4")
			.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
			.arg(clientIPStr).arg(requestId)
			.arg(ErrorResponse::codeString(vr.errorCode)));
		m_metrics.recordRequest(false);
		return HttpResult(vr.httpStatus(),
			stdToQBA(vr.toErrorJson()));
	}

	const CapturedScriptRun run = runCapturedScript(scriptFile, scriptText, argsMap);
	if (!run.loaded) {
		m_metrics.recordRequest(false);
		return HttpResult(400,
			stdToQBA(ErrorResponse::build(
				ErrorCode::SCRIPT_FILE_LOAD_FAILED, JsonStd::qstrToStd(scriptFile))));
	}
	m_sceneRevision.fetchAndAddOrdered(1);  // the script may have changed anything
	const bool success = run.success;

	// Calculate execution duration
	int durationMs = startTime.msecsTo(QTime::currentTime());

	// Record metrics
	m_metrics.recordRequest(success);

	// Log a summary line in the pane with timestamp, IP, status, duration, request ID, and script identifier
	QString logLabel = scriptFile.isEmpty()
		? QString("inline: %1").arg(scriptText.left(40).replace('\n', ' '))
		: QFileInfo(scriptFile).fileName();

	appendLog(QString("[%1] [%2] [%3] [%4ms] [%5] %6")
		.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
		.arg(clientIPStr)
		.arg(success ? "OK" : "ERR")
		.arg(durationMs)
		.arg(requestId)
		.arg(logLabel));

	QString body = buildResponseJson(success,
	                                 success ? run.result : QVariant(),
	                                 run.output,
	                                 success ? QVariant() : QVariant(run.error),
	                                 requestId);
	return HttpResult(200, body.toUtf8());
}

// ─── Script Registry handlers (main thread) ───────────────────────────────────

HttpResult DzScriptServerPane::handleRegisterScript(const QByteArray& jsonBody, const QByteArray& clientIP)
{
	QString clientIPStr = QString::fromUtf8(clientIP.constData(), clientIP.size());

	QVariantMap body;
	std::string parseErrDetail;
	if (!JsonStd::parseObject(jsonBody, body, parseErrDetail)) {
		return HttpResult(400,
			stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));
	}

	QString name        = body.value("name").toString().trimmed();
	QString description = body.value("description").toString().trimmed();
	QString script      = body.value("script").toString();

	ValidationResult nameResult = RequestValidator::validateScriptName(name);
	if (!nameResult.valid)
		return HttpResult(nameResult.httpStatus(),
			stdToQBA(nameResult.toErrorJson()));

	ValidationResult scriptResult = RequestValidator::validateRequiredField(script, "script");
	if (!scriptResult.valid)
		return HttpResult(scriptResult.httpStatus(),
			stdToQBA(scriptResult.toErrorJson()));

	QDateTime registeredAt;
	const bool isUpdate = m_scriptRegistry.registerScript(name, description, script, &registeredAt);

	appendLog(QString("[%1] [%2] [REGISTRY] %3 script: %4")
		.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
		.arg(clientIPStr)
		.arg(isUpdate ? "Updated" : "Registered")
		.arg(name));

	JsonBuilder json;
	json.startObject();
	json.addMember("success",       true);
	json.addMember("id",            name);
	json.addMember("registered_at", registeredAt.toString(Qt::ISODate));
	json.addMember("updated",       isUpdate);
	json.finishObject();
	return HttpResult(200, json.toString().toUtf8());
}

HttpResult DzScriptServerPane::handleRegistryExecuteRequest(
	const QByteArray& scriptText,
	const QByteArray& scriptId,
	const QByteArray& requestBody,
	const QByteArray& clientIP)
{
	QTime   startTime   = QTime::currentTime();
	QString clientIPStr = QString::fromUtf8(clientIP.constData(), clientIP.size());
	QString scriptIdStr = QString::fromUtf8(scriptId.constData(), scriptId.size());
	QString requestId   = MetricsCollector::generateRequestId();

	// Extract args from request body (ignore all other fields — script already resolved)
	QVariantMap argsMap;
	if (!requestBody.isEmpty()) {
		QVariantMap parsedBody;
		std::string parseErrDetail;
		if (JsonStd::parseObject(requestBody, parsedBody, parseErrDetail))
			argsMap = parsedBody.value("args").toMap();
	}

	const CapturedScriptRun run = runCapturedScript(
		QString(), QString::fromUtf8(scriptText.constData(), scriptText.size()), argsMap);
	m_sceneRevision.fetchAndAddOrdered(1);  // the script may have changed anything
	const bool success = run.success;

	int durationMs = startTime.msecsTo(QTime::currentTime());
	m_metrics.recordRequest(success);

	appendLog(QString("[%1] [%2] [%3] [%4ms] [%5] registry:%6")
		.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
		.arg(clientIPStr)
		.arg(success ? "OK" : "ERR")
		.arg(durationMs)
		.arg(requestId)
		.arg(scriptIdStr));

	return HttpResult(200,
		buildResponseJson(success,
		                  success ? run.result : QVariant(),
		                  run.output,
		                  success ? QVariant() : QVariant(run.error),
		                  requestId).toUtf8());
}

HttpResult buildQueuedResponse(const QString& requestId, qint64 submittedAt)
{
	std::string resp = "{\"request_id\":\"";
	resp += JsonStd::escape(JsonStd::qstrToStd(requestId));
	resp += "\",\"status\":\"queued\",\"submitted_at\":\"";
	resp += JsonStd::msecToIso((long long)submittedAt);
	resp += "\"}";
	return HttpResult(200, stdToQBA(resp));
}

HttpResult DzScriptServerPane::handleAsyncExecuteEnqueue(
	const QByteArray& jsonBody,
	const QByteArray& clientIP,
	int maxScriptLengthKB,
	const QByteArray& correlationId)
{
	QVariantMap body;
	std::string parseErrDetail;
	if (!JsonStd::parseObject(jsonBody, body, parseErrDetail)) {
		return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));
	}

	QString scriptFile = body.value("scriptFile").toString();
	QString scriptText = body.value("script").toString();
	const bool bothProvided = !scriptFile.isEmpty() && !scriptText.isEmpty();

	ValidationResult vr = RequestValidator::validateExecuteFields(
		scriptFile, scriptText, maxScriptLengthKB);
	if (!vr.valid)
		return HttpResult(vr.httpStatus(), stdToQBA(vr.toErrorJson()));

	qint64  submittedAt  = 0;
	QString enqueueError;
	QString requestId = enqueueAsyncRequest(
		scriptText, scriptFile, body.value("reportFile").toString(),
		body.value("args").toMap(), "execute",
		QString::fromUtf8(correlationId.constData(), correlationId.size()),
		submittedAt, enqueueError);

	if (requestId.isEmpty())
		return HttpResult(503, stdToQBA(ErrorResponse::build(
			ErrorCode::SERVER_UNAVAILABLE, JsonStd::qstrToStd(enqueueError))));

	if (bothProvided) {
		postLog("[" +
			qbaToStd(clientIP) + "] [WARN] [" +
			JsonStd::qstrToStd(requestId) +
			"] Both scriptFile and script provided; using scriptFile");
	}

	return buildQueuedResponse(requestId, submittedAt);
}

HttpResult DzScriptServerPane::handleAsyncScriptEnqueue(
	const QByteArray& scriptBytes,
	const QByteArray& scriptIdBytes,
	const QByteArray& bodyBytes,
	const QByteArray& correlationId)
{
	QString scriptText = QString::fromUtf8(scriptBytes.constData(), scriptBytes.size());
	QString scriptId   = QString::fromUtf8(scriptIdBytes.constData(), scriptIdBytes.size());

	QVariantMap argsMap;
	QString reportFile;
	if (!bodyBytes.isEmpty()) {
		QVariantMap parsedBody;
		std::string parseErrDetail;
		if (JsonStd::parseObject(bodyBytes, parsedBody, parseErrDetail)) {
			argsMap = parsedBody.value("args").toMap();
			reportFile = parsedBody.value("reportFile").toString();
		}
	}

	qint64  submittedAt  = 0;
	QString enqueueError;
	QString requestId = enqueueAsyncRequest(
		scriptText, QString(), reportFile, argsMap, "script",
		QString::fromUtf8(correlationId.constData(), correlationId.size()),
		submittedAt, enqueueError);

	if (requestId.isEmpty())
		return HttpResult(503, stdToQBA(ErrorResponse::build(
			ErrorCode::SERVER_UNAVAILABLE, JsonStd::qstrToStd(enqueueError))));

	postLog("[ASYNC QUEUED] script:" + JsonStd::qstrToStd(scriptId) +
		" -> " + JsonStd::qstrToStd(requestId));

	return buildQueuedResponse(requestId, submittedAt);
}

// ─── Async Execution (main thread) ───────────────────────────────────────────

// Called on the main thread by AsyncRequestManager's queued wake-up and
// self-reposted after each execution completes to drain the queue.
//
// Blocks the main thread (Qt event loop) for the full duration of each script.
// That is intentional — DAZ Studio's DzScript API is not thread-safe.  HTTP
// threads serving status/result queries go directly to AsyncRequestManager's
// mutex-protected map and are unaffected.
void DzScriptServerPane::processNextAsyncRequest()
{
	QString id, scriptText, scriptFile;
	QVariantMap args;
	if (!m_pAsyncMgr->dequeueNext(id, scriptText, scriptFile, args)) return;

	// Request may have been cancelled while queued
	if (m_pAsyncMgr->isCancelRequested(id)) {
		m_pAsyncMgr->markCancelled(id, "Cancelled before execution started");
		if (id.startsWith("rnd-"))
			endProgressOfCancelledRender(id);
		m_pAsyncMgr->clearCurrent();
		QMetaObject::invokeMethod(this, "processNextAsyncRequest", Qt::QueuedConnection);
		return;
	}

	m_pAsyncMgr->markRunning(id);
	QTime wallClock = QTime::currentTime();

	const bool isRender = id.startsWith("rnd-");
	if (isRender && m_pRenderProgress)
		m_pRenderProgress->notifyStarted(id);

	// Execute the script on the main thread (same path as sync handler)
	m_sCurrentRenderId = isRender ? id : QString();
	const CapturedScriptRun run = runCapturedScript(scriptFile, scriptText, args);
	m_sCurrentRenderId.clear();
	const bool        executed       = run.success;
	const QVariant    scriptResult   = run.result;
	const QString     errorMsg       = run.error;
	const QStringList capturedOutput = run.output;

	int durationMs = wallClock.msecsTo(QTime::currentTime());

	// Bump before markCompleted so a client that sees the job finish also
	// sees the revision that covers its effects. A failed script may still
	// have changed the scene before it threw, so bump either way.
	m_sceneRevision.fetchAndAddOrdered(1);

	bool wasCancelled = false;
	QString renderError;  // set when a render ran but didn't succeed (rzp1)
	m_pAsyncMgr->markCompleted(id, executed, scriptResult, capturedOutput, errorMsg,
	                           wasCancelled, renderError);
	m_pAsyncMgr->clearCurrent();
	const bool succeeded = executed && !wasCancelled && renderError.isEmpty();

	if (isRender && m_pRenderProgress) {
		if (succeeded) {
			// markCompleted() declared the render's files (every frame for an
			// animation), so size those rather than the {frame} template path.
			QStringList outputFiles;
			QVariantList manifest;
			QString manifestStatus;
			if (m_pAsyncMgr->artifactManifest(id.toStdString(), manifest, manifestStatus)) {
				for (int i = 0; i < manifest.size(); ++i) {
					const QString path = manifest[i].toMap().value("path").toString();
					if (!path.isEmpty())
						outputFiles.append(path);
				}
			}
			m_pRenderProgress->notifyCompleted(id, durationMs, outputFiles);
		}
		else
			m_pRenderProgress->notifyFailed(id,
				wasCancelled ? ErrorCode::JOB_CANCELLED : ErrorCode::SCRIPT_ERROR,
				renderError.isEmpty() ? errorMsg : renderError, durationMs);
	}

	m_metrics.recordRequest(succeeded);

	appendLog(QString("[%1] [ASYNC] [%2] [%3ms] %4")
		.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
		.arg(wasCancelled ? "CANCEL" : (succeeded ? "OK" : "ERR"))
		.arg(durationMs)
		.arg(id));

	// Drain the queue
	QMetaObject::invokeMethod(this, "processNextAsyncRequest", Qt::QueuedConnection);
}

// Removes finished (and stale) requests older than 1 hour, and marks stale
// any request that has been running for longer than
// the "Stuck Job Timeout" setting (see failStaleRunning()).
// Fired by m_pCleanupTimer every 5 minutes on the main thread.
void DzScriptServerPane::cleanupExpiredRequests()
{
	int removed = m_pAsyncMgr->cleanupExpired();
	if (removed > 0) {
		appendLog(QString("[INFO] Async cleanup: removed %1 expired request(s)").arg(removed));
	}

	int stale = m_pAsyncMgr->failStaleRunning((qint64)m_nStaleJobTimeoutMin * 60 * 1000);
	if (stale > 0) {
		appendLog(QString("[WARN] Async cleanup: %1 request(s) stuck running past %2 min, marked stale")
			.arg(stale).arg(m_nStaleJobTimeoutMin));
	}
}

// Called on the main thread via killRenderRequested signal from AsyncRequestManager.
// Keeps the DAZ API call off HTTP threads.
void DzScriptServerPane::killRenderOnMainThread()
{
	DzRenderMgr* renderMgr = dzApp ? dzApp->getRenderMgr() : nullptr;
	if (renderMgr && renderMgr->isRendering()) {
		DzRenderer* renderer = renderMgr->getActiveRenderer();
		if (renderer) renderer->killRender();
	}
}
