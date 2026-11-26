// DzScriptServerPane: construction, server start/stop, print() capture,
// health/metrics/capabilities, main-thread busy state and scene I/O.
//
// The other pane members live by concern (W21 split):
//   PaneUi.cpp            widgets, settings load/save, UI slots, log view
//   HttpJobRoute.cpp      httplib <-> HttpContext, runJobRoute(), runSyncJobRoute()
//   PaneRoutes.cpp        setupRoutes() route table, artifact thumbnails
//   PluginRouteBridge.cpp companion-plugin registration and catch-all routes
//   ScriptJobs.cpp        execute/registry/async handlers, async queue drain
//   RenderJobs.cpp        render / render batch / animation submission
//   RenderScriptBuilder.* DazScript generated for render jobs (no pane state)
// PaneInternal.h holds the includes and helpers they share.
#include "PaneInternal.h"

// ─── DzScript execution ────────────────────────────────────────────────────────
// Contract and SDK4/SDK6 differences: see ScriptRunResult in PaneInternal.h.
ScriptRunResult runDazScript(
	DzScript* script,
	const QVariantMap& argsMap,
	const QString& scriptFilename)
{
	// Hold back main-thread calls the script's event pumping would otherwise
	// run nested inside it (daz-script-server-29gd).
	MainThreadCall::ScriptScope scriptScope;
	ScriptRunResult r;
#if DAZ_SDK_MAJOR_VERSION >= 6
	// On SDK6, evaluate() (needed for a usable completion value — see above)
	// does not route print() through any dzApp signal at all, unlike
	// execute() (verified empirically: print() text reaches DAZ Studio's own
	// log via execute(), but not via evaluate()). So print() itself is
	// shimmed as a local JS function that appends to an array, and the whole
	// thing — result, captured output, and any caught error — comes back as
	// one JSON blob. This also sidesteps QJSValue::isError(), which only
	// recognizes actual Error objects: a bare `throw "string"` would
	// otherwise be missed and misreported as success.
	QVariantList argsList;
	argsList << QVariant(argsMap);
	QString argsJson = QString::fromStdString(JsonStd::variantToJson(QVariant(argsList)));
	// evaluate() runs the wrapper as anonymous source on SDK6, so the engine's
	// built-in getScriptFileName() sees no filename even after loadFromFile().
	// Carry the request's explicit filename into the evaluated program. Do not
	// read it back from the reused DzScript instance: the SDK does not document
	// whether clear() resets a filename retained by a preceding file-backed job.
	// This also keeps file-backed scripts' relative-loader helpers working while
	// guaranteeing that an inline job reports an empty filename.
	QString filenameJson = QString::fromStdString(
		JsonStd::variantToJson(QVariant(scriptFilename)));
	QString codeLiteral = QString::fromStdString(
		"\"" + JsonStd::escape(JsonStd::qstrToStd(script->getCode())) + "\"");
	QString shimmed = QString(
		"var __dss_output = [];\n"
		"function print(msg) { __dss_output.push(String(msg)); }\n"
		"function getArguments(){ return %1; }\n"
		"function getScriptFileName(){ return %2; }\n"
		"var __dss_result = null, __dss_error = null, __dss_errorLine = 0;\n"
		"try {\n"
		"  __dss_result = eval(%3);\n"
		"} catch (e) {\n"
		"  __dss_error = (e && e.message !== undefined) ? String(e.message) : String(e);\n"
		"  __dss_errorLine = (e && e.lineNumber) ? e.lineNumber : 0;\n"
		"}\n"
		"JSON.stringify({ result: __dss_result, output: __dss_output, "
		"error: __dss_error, errorLine: __dss_errorLine });"
	).arg(argsJson, filenameJson, codeLiteral);

	QJSValue evalResult = script->evaluate(shimmed);
	if (evalResult.isError()) {
		// Our own wrapper failed to parse/run — a bug in the shim above,
		// not the user's script (that path is caught by the try/catch).
		r.errorMessage = evalResult.toString();
		r.errorLine    = evalResult.property("lineNumber").toInt();
	} else {
		QJsonDocument doc = QJsonDocument::fromJson(evalResult.toString().toUtf8());
		QJsonObject   obj = doc.object();
		for (const QJsonValue& v : obj.value("output").toArray())
			r.output << v.toString();

		QJsonValue errVal = obj.value("error");
		if (errVal.isNull() || errVal.isUndefined()) {
			r.success = true;
			r.result  = obj.value("result").toVariant();
		} else {
			r.errorMessage = errVal.toString();
			r.errorLine    = obj.value("errorLine").toInt();
		}
	}
#else
	// Avoid execute(args) -> DzScriptContext::setArgs(), which corrupts
	// dzcore's heap when called repeatedly on a reused DzScript/context
	// (verified via live debugger: ntdll!RtlFreeHeap -> MSVCR100!free ->
	// dzcore!DzScriptContext::setArgs -> DzScript::doExecute ->
	// DzScript::execute, triggered by the persistent-instance reuse pattern
	// below). Inject args via a getArguments() shim instead — same technique
	// as the SDK6 path above — and call the no-arg execute() overload, which
	// never touches DzScriptContext::setArgs at all.
	QVariantList argsList;
	argsList << QVariant(argsMap);
	QString argsJson = QString::fromStdString(JsonStd::variantToJson(QVariant(argsList)));
	QString filenameJson = QString::fromStdString(
		JsonStd::variantToJson(QVariant(scriptFilename)));
	QString shimmed = QString(
		"function getArguments(){ return %1; }\n"
		"function getScriptFileName(){ return %2; }\n%3")
		.arg(argsJson, filenameJson, script->getCode());
	script->setCode(shimmed);
	if (script->execute()) {
		r.success = true;
		r.result  = script->result();
	} else {
		r.errorMessage = script->errorMessage();
		r.errorLine    = script->errorLine();
	}
#endif
	return r;
}

// ─── ServerListenThread ───────────────────────────────────────────────────────
// Defined here (not in the header) to keep httplib contained in this .cpp.

class ServerListenThread : public QThread {
public:
	ServerListenThread(httplib::Server* pServer,
	                   const std::string& host, int port,
	                   QObject* parent = nullptr)
		: QThread(parent), m_pServer(pServer), m_sHost(host), m_nPort(port) {}
	static void msSleep(unsigned long ms) { QThread::msleep(ms); }
protected:
	void run() override { m_pServer->listen(m_sHost.c_str(), m_nPort); }
private:
	httplib::Server* m_pServer;
	std::string      m_sHost;
	int              m_nPort;
};

// ─── DzScriptServerPane ───────────────────────────────────────────────────────

DzScriptServerPane::DzScriptServerPane()
	: DzPane("Daz Script Server")
	, m_pServer(nullptr)
	, m_pServerThread(nullptr)
	, m_nPort(ServerSettings().port)
	, m_sHost("127.0.0.1")
	, m_bRunning(false)
	, m_bCapturingLog(false)
	, m_nTimeoutSec(ServerSettings().timeoutSec)
	, m_nActiveRequests(0)
	, m_bAutoStart(false)
	, m_nMaxConcurrentRequests(ServerConfig::DEFAULT_MAX_CONCURRENT_REQUESTS)
	, m_nMaxBodySizeMB(ServerConfig::DEFAULT_MAX_BODY_SIZE_MB)
	, m_nMaxScriptLengthKB(ServerConfig::DEFAULT_MAX_SCRIPT_LENGTH_KB)
	, m_nStaleJobTimeoutMin(ServerConfig::ASYNC_STALE_RUNNING_TIMEOUT_MIN)
	, m_rateLimiter(ServerConfig::DEFAULT_RATE_LIMIT_MAX, ServerConfig::DEFAULT_RATE_LIMIT_WINDOW)
	, m_pAsyncMgr(nullptr)
	, m_pCleanupTimer(nullptr)
	, m_pProgressPollTimer(nullptr)
	, m_progressBusy(ProgressIdle)
	, m_pEventBroker(nullptr)
	, m_pRenderProgress(nullptr)
	, m_pEventClientsLabel(nullptr)
	, m_pLogView(nullptr)
	, m_pPersistentScript(nullptr)
{
	// HttpResult crosses threads in queued calls (MainThreadCall, plugin slots).
	qRegisterMetaType<HttpResult>("HttpResult");

	// m_pPersistentScript is lazily created on first use (see
	// ensurePersistentScript()) rather than here — this constructor runs very
	// early during DAZ Studio startup (panes get restored before the app is
	// fully initialized), and DzScript may depend on subsystems that aren't
	// ready yet at this point.

	// Load settings and token
	loadSettings();

	// m_pLogView doesn't exist yet (appendLog() would drop these), so the
	// messages — including a crypto-API failure — are logged after updateUI().
	QStringList tokenMsgs;
	m_auth.loadOrGenerateToken(tokenMsgs);

	// ── Async request manager ─────────────────────────────────────────────────
	// Pass 'this' so AsyncRequestManager can invoke processNextAsyncRequest()
	// and killRenderOnMainThread() via QMetaObject::invokeMethod internally.
	m_pAsyncMgr = new AsyncRequestManager(this);

	// ── Async cleanup timer ───────────────────────────────────────────────────
	// Created here so it lives on the main thread (correct for QTimer).
	// Started in startServer(), stopped in stopServer().
	m_pCleanupTimer = new QTimer(this);
	connect(m_pCleanupTimer, SIGNAL(timeout()), this, SLOT(cleanupExpiredRequests()));
	m_pProgressPollTimer = new QTimer(this);
	connect(m_pProgressPollTimer, SIGNAL(timeout()), this, SLOT(pollProgressBusy()));

	buildUi();
	updateUI();

	for (const QString& msg : tokenMsgs)
		appendLog(msg);

	// Register this pane on the application object so companion plugins can find
	// it without walking the widget tree (which may fail across DLL boundaries).
	// Bridge plugins look up: qApp->property("DzScriptServerPane").value<QObject*>()
	if (QCoreApplication::instance()) {
		QCoreApplication::instance()->setProperty("DzScriptServerPane",
		                                          QVariant::fromValue<QObject*>(this));
		appendLog("[INFO] DzScriptServerPane registered on qApp for companion plugin discovery.");
	} else {
		appendLog("[WARN] QCoreApplication not available — companion plugins may not find this pane.");
	}

	// Auto-start server if enabled
	if (m_bAutoStart) {
		appendLog("[INFO] Auto-starting server...");
		startServer();
	}
}

DzScriptServerPane::~DzScriptServerPane()
{
	if (QCoreApplication::instance())
		QCoreApplication::instance()->setProperty("DzScriptServerPane", QVariant());
	stopServer();
	saveSettings();
	// Not a QObject child: delete it ourselves, after stopServer() has
	// cancelled its jobs and no HTTP worker can reach it.
	delete m_pAsyncMgr;
	m_pAsyncMgr = nullptr;
	DzScriptDeleter::cleanup(m_pPersistentScript);
}

DzScript* DzScriptServerPane::ensurePersistentScript()
{
	if (!m_pPersistentScript) {
		m_pPersistentScript = new DzScript("DazScriptServer");
		m_pPersistentScript->setReuseInterpreter(true);
	}
	return m_pPersistentScript;
}

// ─── Start / Stop ─────────────────────────────────────────────────────────────

void DzScriptServerPane::onStartClicked()
{
	m_nPort = m_pPortSpin->value();
	m_sHost = m_pHostEdit->text();
	m_nTimeoutSec = m_pTimeoutSpin->value();

	// Capture advanced limit settings
	m_nMaxConcurrentRequests = m_pMaxConcurrentSpin->value();
	m_nMaxBodySizeMB = m_pMaxBodySizeSpin->value();
	m_nMaxScriptLengthKB = m_pMaxScriptLengthSpin->value();

	// Capture IP whitelist settings
	m_ipWhitelist.setEnabled(m_pIpWhitelistCheck->isChecked());
	m_ipWhitelist.setWhitelist(m_pIpWhitelistEdit->text());

	// Capture artifact folder settings (resolved in startServer())
	m_artifactRoots.setEnabled(m_pArtifactRootsCheck->isChecked());
	m_artifactRoots.configure(m_pArtifactRootsEdit->text());

	// Capture rate limit settings
	m_rateLimiter.setEnabled(m_pRateLimitCheck->isChecked());
	m_rateLimiter.configure(m_pRateLimitMaxSpin->value(), m_pRateLimitWindowSpin->value());

	saveSettings();
	startServer();
}

void DzScriptServerPane::onStopClicked()
{
	stopServer();
}

void DzScriptServerPane::startServer()
{
	// m_pServerThread is non-null while teardownServer() is joining it (it
	// pumps events, so a queued start could otherwise run mid-teardown).
	if (m_bRunning || m_pServerThread)
		return;

	// ── Fail-fast: verify critical startup requirements ──────────────────────
	//
	// Refuse to start if any critical component cannot be initialised safely.
	// Each check logs a detailed error and shows a dialog before returning.

	// 1. DAZ SDK availability
	if (!dzApp) {
		appendLog("[CRITICAL] Cannot start server: DAZ Studio application object is not available.");
		QMessageBox::critical(this, tr("Startup Error"),
			tr("Cannot start server: DAZ Studio application object (dzApp) is null.\n\n"
			   "This should not happen in a normal plugin context. "
			   "Try restarting DAZ Studio."));
		return;
	}

	// 2. Crypto / token availability
	if (m_auth.isEnabled() && (m_auth.getToken().isEmpty() || m_auth.getToken().length() < 32)) {
		appendLog("[CRITICAL] Cannot start server: No valid API token available. "
		          "The cryptographic RNG may have failed during plugin initialisation.");
		QMessageBox::critical(this, tr("Security Error"),
			tr("Cannot start server without a valid API token.\n\n"
			   "The cryptographic random number generator failed to produce a secure token. "
			   "This may indicate a system security configuration issue.\n\n"
			   "Try disabling authentication temporarily, or check system logs for errors."));
		return;
	}

	// 3. Token file directory writability
	{
		QString tokenPath = AuthenticationService::getTokenFilePath();
		QFileInfo tokenDir(tokenPath);
		QString   dirPath = tokenDir.absolutePath();
		QFile     probe(dirPath + "/.dzsrv_probe");
		if (!probe.open(QIODevice::WriteOnly)) {
			appendLog(QString("[WARN] Token file directory may not be writable: %1 — "
			                  "token persistence may fail").arg(dirPath));
			// Non-fatal: server can still run; token was already loaded into memory.
		} else {
			probe.close();
			probe.remove();
		}
	}

	// 4. Artifact trust boundary: resolve the allowed folders now, so a folder
	//    created since the settings were loaded counts, and log what applies.
	{
		QStringList warnings;
		m_artifactRoots.configure(m_artifactRoots.rawList(), &warnings);
		const QString deniedDir = QFileInfo(AuthenticationService::getTokenFilePath()).absolutePath();
		if (!m_artifactRoots.setDeniedDir(deniedDir))
			appendLog(QString("[WARN] Could not resolve %1; artifact downloads re-check it per request and are refused while it exists unresolved").arg(deniedDir));
		for (const QString& w : warnings)
			appendLog(QString("[WARN] %1").arg(w));
		if (m_artifactRoots.isEnabled())
			appendLog(QString("[INFO] Artifact folders: %1").arg(m_artifactRoots.effectiveRoots().join("; ")));
		else
			appendLog("[WARN] Artifact folder restriction disabled - any declared output can be served (~/.daz3d still refused)");
	}

	m_pServer = new httplib::Server();
	m_pServer->set_read_timeout(m_nTimeoutSec, 0);
	// SSE connections are long-lived; the write timeout must exceed the
	// keepalive / pop timeout (ServerConfig static_asserts it).
	m_pServer->set_write_timeout(ServerConfig::HTTP_WRITE_TIMEOUT_SEC, 0);

	// Cap request bodies while httplib is still reading them. Without this,
	// httplib buffers up to its 100 MB compile-time default on every route before
	// any middleware runs. The spin box is disabled while the server is running,
	// so the value can't change under the worker threads.
	const size_t maxBodyBytes = ServerConfig::mbToBytes(m_nMaxBodySizeMB);
	m_pServer->set_payload_max_length(maxBodyBytes);

	// New identity for this run. Jobs and idempotency records from an earlier
	// run are not resumable, and the changed ID is how clients find that out.
	{
		QString hex = SecureRandom::generateHexToken(8);
		if (hex.isEmpty())
			hex = QUuid::createUuid().toString().mid(1, 8) + QUuid::createUuid().toString().mid(1, 8);
		m_serverInstanceId = ("srv-" + hex).toLatin1();
	}
	m_sceneRevision.fetchAndStoreOrdered(0);
	m_idempotency.clear();
	// QImageReader is QtGui: list the decodable formats here, on the main
	// thread, before any HTTP worker exists.
	m_thumbnailExtensions = ArtifactThumbnail::readableExtensions();
	m_thumbnailCache.clear();
	m_pAsyncMgr->setServerInstanceId(QString::fromLatin1(m_serverInstanceId));

	// Every error response carries the JSON error envelope. httplib produces
	// some errors itself with an empty body (413 at the payload cap, 400 for a
	// malformed request, 500 for an exception escaping a handler); fill those
	// in. Bodies a handler already wrote are left alone.
	const int maxBodyMB = m_nMaxBodySizeMB;
	m_pServer->set_error_handler(
		[maxBodyMB, maxBodyBytes](const httplib::Request&, httplib::Response& res) {
			if (!res.body.empty())
				return httplib::Server::HandlerResponse::Unhandled;
			std::string body;
			if (res.status == 413) {
				const std::string detail =
					"Body exceeds the maximum of " + std::to_string(maxBodyMB) +
					" MB (" + std::to_string(maxBodyBytes) + " bytes)";
				body = ErrorResponse::build(ErrorCode::BODY_TOO_LARGE, detail);
			} else if (res.status == 404) {
				body = ErrorResponse::build(ErrorCode::ROUTE_NOT_FOUND);
			} else if (res.status == 503) {
				body = ErrorResponse::build(ErrorCode::SERVER_UNAVAILABLE);
			} else if (res.status >= 500) {
				body = ErrorResponse::build(ErrorCode::INTERNAL_ERROR);
			} else {
				body = ErrorResponse::build(ErrorCode::BAD_REQUEST,
					"HTTP " + std::to_string(res.status));
			}
			res.set_content(body, "application/json");
			return httplib::Server::HandlerResponse::Handled;
		});

	// Identity headers on every response, including errors from middleware.
	// X-Correlation-Id is echoed when the client sent a valid one; job routes
	// set it themselves (with a generated ID when the client sent none).
	const std::string instanceIdHeader(m_serverInstanceId.constData(), m_serverInstanceId.size());
	m_pServer->set_post_routing_handler(
		[instanceIdHeader](const httplib::Request& req, httplib::Response& res) {
			res.set_header("X-Server-Instance-Id", instanceIdHeader);
			if (!res.has_header("X-Correlation-Id")) {
				const std::string corr = req.get_header_value("X-Correlation-Id");
				if (IdempotencyCache::isValidKey(QByteArray(corr.c_str(), (int)corr.size())))
					res.set_header("X-Correlation-Id", corr);
			}
		});

	// Limit concurrent connections to prevent resource exhaustion
	// cpp-httplib spawns a thread per request; limit keep-alive to reduce thread buildup
	m_pServer->set_keep_alive_max_count(ServerConfig::HTTP_KEEP_ALIVE_MAX_COUNT);
	m_pServer->set_keep_alive_timeout(ServerConfig::HTTP_KEEP_ALIVE_TIMEOUT_SEC);

	// Listening-socket options (W9). On Windows SO_REUSEADDR lets another
	// local process bind the same address/port while we listen and steal
	// connections (tokens included), so take the port exclusively instead;
	// Windows has no TIME_WAIT rebind problem to work around. On POSIX,
	// SO_REUSEADDR only allows rebinding over TIME_WAIT and cannot be used to
	// hijack an active listener, so keep it for fast restarts.
	m_pServer->set_socket_options([](socket_t sock) {
		int yes = 1;
#ifdef _WIN32
		setsockopt(sock, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (char*)&yes, sizeof(yes));
#else
		setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
#endif
		return 0;
	});

	setupRoutes();

	m_aHostUtf8 = m_sHost.toUtf8();
	m_pServerThread = new ServerListenThread(
		m_pServer,
		std::string(m_aHostUtf8.constData()),
		m_nPort,
		this);

	// Check if port is available before starting
	if (!m_pServer->is_valid()) {
		appendLog(QString("[ERROR] Failed to initialize server: Socket creation failed. Check system resources and network configuration."));
		delete m_pServer;
		m_pServer = nullptr;
		delete m_pServerThread;
		m_pServerThread = nullptr;
		return;
	}

	// SSE routes dereference both brokers on worker threads, so they must
	// exist before the listen thread accepts its first connection.
	m_pEventBroker = new SceneEventBroker(this);
	m_pEventBroker->setRevisionCounter(&m_sceneRevision);
	m_pEventBroker->start();

	m_pRenderProgress = new RenderProgressBroker();

	m_pServerThread->start();

	ServerListenThread::msSleep(ServerConfig::SERVER_BIND_WAIT_MS);

	// Check if server bound successfully
	if (!m_pServer->is_running()) {
		appendLog(QString("[ERROR] Failed to bind to %1:%2 - Port is already in use by another application. Try a different port or stop the conflicting service.")
			.arg(m_sHost).arg(m_nPort));
		// listen() may still be running on the thread: stop and join it
		// before freeing the server it uses.
		teardownServer();
		return;
	}

	m_bRunning = true;

	// Prime the snapshot GET /capabilities serves while the main thread is busy.
	refreshCapabilitiesSnapshot();

	updateUI();
	appendLog(QString("[%1] Server started on %2:%3 (timeout: %4s)")
		.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
		.arg(m_sHost)
		.arg(m_nPort)
		.arg(m_nTimeoutSec));

	m_pCleanupTimer->start(ServerConfig::ASYNC_CLEANUP_INTERVAL_MIN * 60 * 1000);
	pollProgressBusy();
	m_pProgressPollTimer->start(ServerConfig::PROGRESS_POLL_INTERVAL_MS);
}

void DzScriptServerPane::teardownServer()
{
	// 1. Stop the event and progress brokers: unblocks all SSE pop() calls so
	//    content-provider callbacks drain quickly before the server is torn down.
	//    Not deleted yet: SSE resource-releaser lambdas hold raw pointers to them.
	if (m_pRenderProgress)
		m_pRenderProgress->stopAll();
	if (m_pEventBroker)
		m_pEventBroker->stop();

	// 2. Close the listening socket and flag shutdown, so listen() returns and
	//    chunked write loops exit. m_pServer stays alive: run() still uses it.
	if (m_pServer)
		m_pServer->stop();

	// 3. Join the listen thread. httplib joins every request-handler thread
	//    before listen() returns. Handlers may be waiting on a MainThreadCall
	//    posted to this (main) thread, so keep delivering non-input events
	//    while waiting, or they could only finish by timing out.
	bool joined = true;
	if (m_pServerThread) {
		QElapsedTimer timer;
		timer.start();
		while (!m_pServerThread->wait(50)) {
			if (timer.elapsed() >= ServerConfig::SERVER_THREAD_STOP_TIMEOUT_MS) {
				joined = false;
				break;
			}
			QCoreApplication::processEvents(QEventLoop::ExcludeUserInputEvents, 50);
		}
	}

	if (!joined) {
		// terminate() would kill a thread that may hold locks (undefined
		// behaviour). Leak the thread, server and brokers instead: still-running
		// handlers keep valid pointers. A restart builds new ones.
		appendLog("[WARN] Server thread did not stop within the timeout; leaking it "
		          "rather than terminating it. Restart DAZ Studio if the port stays in use.");
		m_pServerThread = nullptr;
		m_pServer = nullptr;
		m_pRenderProgress = nullptr;
		m_pEventBroker = nullptr;
		return;
	}

	// 4. run() has returned and every handler thread is joined: free it all.
	delete m_pServerThread;
	m_pServerThread = nullptr;
	delete m_pServer;
	m_pServer = nullptr;
	delete m_pRenderProgress;
	m_pRenderProgress = nullptr;
	delete m_pEventBroker;
	m_pEventBroker = nullptr;
}

void DzScriptServerPane::stopServer()
{
	if (!m_bRunning)
		return;

	// Stop async cleanup timer
	m_pCleanupTimer->stop();
	m_pProgressPollTimer->stop();
	m_progressBusy.store(ProgressIdle);

	teardownServer();

	// Clear rate limit state
	m_rateLimiter.reset();

	// Mark any queued/running async requests as cancelled, then stop the cleanup timer.
	m_pAsyncMgr->cancelAllPending("Server stopped");
	m_pCleanupTimer->stop();

	m_bRunning = false;
	m_metrics.saveToSettings();
	updateUI();
	updateActiveRequestsLabel();
	updateEventClientsLabel();
	appendLog("Server stopped.");
}

void DzScriptServerPane::handleMainThreadCall(qulonglong call)
{
	MainThreadCall::runOnMainThread(this,
		reinterpret_cast<MainThreadCall::Call*>(static_cast<quintptr>(call)));
}

// ─────────────────────────────────────────────────────────────────────────────

void DzScriptServerPane::onMessagePosted(const QString& msg)
{
	if (!m_bCapturingLog)
		return;

	// Limit captured output to prevent memory exhaustion from excessive print() calls
	if (m_aCapturedLogLines.size() < ServerConfig::MAX_CAPTURED_LINES) {
		m_aCapturedLogLines.append(msg);
	} else if (m_aCapturedLogLines.size() == ServerConfig::MAX_CAPTURED_LINES) {
		// Add a warning message once when limit is reached
		m_aCapturedLogLines.append(
			QString("[WARNING] Output truncated: maximum %1 lines captured")
				.arg(ServerConfig::MAX_CAPTURED_LINES));
	}
	// Silently discard additional lines beyond limit

	// Frame-boundary progress for animation renders: buildAnimationRenderScript()
	// prints "[DAZPY_FRAME] n/total" right before each frame's doRender() call.
	// Iray itself exposes no per-percent progress signal (see
	// RenderProgressBroker.h), so this print-marker is the only real progress
	// source available; only intercept it while a render is actually running.
	if (!m_sCurrentRenderId.isEmpty()) {
#if DAZ_SDK_MAJOR_VERSION >= 6
		static const QRegularExpression frameRx("^\\[DAZPY_FRAME\\] (\\d+)/(\\d+)$");
		QRegularExpressionMatch frameMatch = frameRx.match(msg);
		bool frameMatched = frameMatch.hasMatch();
		QString frameCap1 = frameMatch.captured(1);
		QString frameCap2 = frameMatch.captured(2);
#else
		static QRegExp frameRx("^\\[DAZPY_FRAME\\] (\\d+)/(\\d+)$");
		bool frameMatched = frameRx.indexIn(msg) == 0;
		QString frameCap1 = frameRx.cap(1);
		QString frameCap2 = frameRx.cap(2);
#endif
		if (frameMatched) {
			int frame = frameCap1.toInt();
			int total = frameCap2.toInt();
			if (total > 0) {
				if (m_pRenderProgress)
					m_pRenderProgress->notifyProgress(m_sCurrentRenderId, frame, total);
				if (m_pAsyncMgr)
					m_pAsyncMgr->updateFrameProgress(m_sCurrentRenderId, frame, total);
			}
		}
	}

	// Any printed line from an async job is a sign of life (last_activity_at).
	// Studio 4 only: Studio 6 shims print() into an array (runDazScript), so
	// this slot doesn't see job output there; report-file writes cover it.
	if (m_pAsyncMgr)
		m_pAsyncMgr->touchCurrent();
}

// ─── JSON helpers (main thread only) ─────────────────────────────────────────

QString DzScriptServerPane::buildResponseJson(bool success,
                                              const QVariant& result,
                                              const QStringList& output,
                                              const QVariant& error,
                                              const QString& requestId)
{
	JsonBuilder json;
	json.startObject();

	json.addMember("success", success);
	json.addMember("result", result);

	// Build output array
	QVariantList outputList;
	for (const QString& line : output)
		outputList.append(QVariant(line));
	json.addMember("output", QVariant(outputList));

	json.addMember("error", error);
	if (!success) {
		// Same error envelope as HTTP-level failures (ErrorResponse).
		json.addMember("error_code", ErrorResponse::codeString(ErrorCode::SCRIPT_ERROR));
		json.addMember("retryable", ErrorResponse::retryable(ErrorCode::SCRIPT_ERROR));
	}

	// Add request ID if provided (for debugging/correlation)
	if (!requestId.isEmpty()) {
		json.addMember("request_id", requestId);
	}

	json.finishObject();
	return json.toString();
}

// ─── Metrics and Monitoring ───────────────────────────────────────────────────

std::string DzScriptServerPane::getHealthJson() const
{
	// Build with std::string only — called from httplib worker threads where Qt string ops are unsafe.
	std::string s = "{\"status\":\"ok\",\"version\":\"";
	s += DZSRV_VERSION_STR;
	s += "\",\"running\":";
	s += m_bRunning ? "true" : "false";
	s += ",\"auth_enabled\":";
	s += m_auth.isEnabled() ? "true" : "false";
	s += ",\"active_requests\":";
	s += std::to_string((int)m_nActiveRequests);
	s += ",\"uptime_seconds\":";
	s += std::to_string((long long)m_metrics.getUptimeSeconds());
	s += ",\"server_instance_id\":\"";
	s.append(m_serverInstanceId.constData(), m_serverInstanceId.size());
	s += "\",\"scene_revision\":";
	s += std::to_string(sceneRevision());
	s += "}";
	return s;
}

std::string DzScriptServerPane::getMetricsJson() const
{
	return m_metrics.toJson((int)m_nActiveRequests);
}

// ─── Capabilities (GET /capabilities) ─────────────────────────────────────────

QByteArray DzScriptServerPane::buildCapabilitiesJson(const QString& engineSource) const
{
	// Main thread only: reads GUI-owned settings (see Capabilities.h).
	Capabilities::Inputs in;
	in.serverInstanceId      = m_serverInstanceId;
	m_pluginRegistry.snapshot(&in.pluginRoutes, &in.companions);
	in.maxBodySizeMB         = m_nMaxBodySizeMB;
	in.maxScriptLengthKB     = m_nMaxScriptLengthKB;
	in.maxConcurrentRequests = m_nMaxConcurrentRequests;
	in.asyncMaxQueueDepth    = m_pAsyncMgr ? m_pAsyncMgr->maxQueueDepth()
	                                       : AsyncRequestManager::DEFAULT_MAX_QUEUE_DEPTH;
	in.idempotencyTtlSeconds = m_idempotency.ttlSeconds();
	in.staleJobTimeoutMin    = m_nStaleJobTimeoutMin;
	in.thumbnailExtensions   = m_thumbnailExtensions;
	in.rateLimitEnabled      = m_rateLimiter.isEnabled();
	in.rateLimitMax          = m_pRateLimitMaxSpin ? m_pRateLimitMaxSpin->value()
	                                               : ServerConfig::DEFAULT_RATE_LIMIT_MAX;
	in.rateLimitWindowSeconds = m_pRateLimitWindowSpin ? m_pRateLimitWindowSpin->value()
	                                                   : ServerConfig::DEFAULT_RATE_LIMIT_WINDOW;
	in.authEnabled           = m_auth.isEnabled();
	in.ipWhitelistEnabled    = m_ipWhitelist.isEnabled();
	in.artifactRootsEnabled  = m_artifactRoots.isEnabled();
	in.artifactRoots         = m_artifactRoots.effectiveRoots();
	return Capabilities::build(in, engineSource);
}

void DzScriptServerPane::refreshCapabilitiesSnapshot()
{
	const QByteArray body = buildCapabilitiesJson(QString("snapshot"));
	QMutexLocker lock(&m_capabilitiesMutex);
	m_capabilitiesSnapshot = body;
}

QByteArray DzScriptServerPane::capabilitiesSnapshot() const
{
	QMutexLocker lock(&m_capabilitiesMutex);
	return m_capabilitiesSnapshot;
}

HttpResult DzScriptServerPane::handleCapabilitiesRequest()
{
	refreshCapabilitiesSnapshot();
	return HttpResult(200, buildCapabilitiesJson(QString("live")));
}

bool DzScriptServerPane::isMainThreadBusy() const
{
	if (m_pEventBroker && m_pEventBroker->isBusy()) return true;
	// DzScene's load/save/clear/render signals don't cover every busy window --
	// observed live: DAZ Studio keeps streaming in referenced/lazy-loaded nodes
	// on the main thread for several seconds after sceneLoaded() fires, with no
	// DzScene signal marking that tail. DzProgress/DzBackgroundProgress back the
	// progress indicator DAZ Studio itself shows for exactly that kind of work,
	// so poll it as a second, independent busy signal.
	// Sampled on the main thread by pollProgressBusy(): DzProgress is not
	// safe to call from an HTTP worker.
	return m_progressBusy.load() != ProgressIdle;
}

void DzScriptServerPane::pollProgressBusy()
{
	m_progressBusy.store(DzBackgroundProgress::isActive() ? ProgressBackground
	                     : DzProgress::isActive()         ? ProgressForeground
	                                                      : ProgressIdle);
}

std::string DzScriptServerPane::mainThreadBusyMessage() const
{
	if (m_pEventBroker && m_pEventBroker->busyReason() != MainThreadBusy::Idle) {
		return MainThreadBusy::reasonMessage(m_pEventBroker->busyReason());
	}
	// isMainThreadBusy()'s second check (DzProgress/DzBackgroundProgress) has
	// no matching SceneEventBroker reason -- distinguish the two paths so a
	// caller isn't left with a generic message for what's usually several
	// seconds of DAZ Studio streaming in lazy-loaded content after a scene
	// load, not a real hang. Neither DzProgress nor DzBackgroundProgress
	// exposes a readable status/info string (setInfo() has no getter), so
	// this is the most specific message obtainable from the SDK.
	const int progress = m_progressBusy.load();
	if (progress == ProgressBackground) {
		return "DAZ Studio is busy loading background content (e.g. lazy-loaded/referenced scene assets)";
	}
	if (progress == ProgressForeground) {
		return "DAZ Studio is showing a progress dialog for a foreground operation";
	}
	return "DAZ Studio is busy";
}

// ─── Scene I/O ────────────────────────────────────────────────────────────────

// RAII guard for MainThreadBusy state, for handlers that perform a long
// synchronous operation without going through the DzScene signal that would
// normally bracket it (e.g. save-copy's QFile::copy fast path, which never
// calls DzScene::saveScene() and so never fires sceneSaveStarting/sceneSaved).
// enterBusy()/exitBusy() are depth-counted, so nesting with signal-driven
// busy tracking (e.g. a saveScene() call also covered by this same guard) is safe.
struct BusyScope {
	SceneEventBroker* broker;

	BusyScope(SceneEventBroker* b, MainThreadBusy::Reason reason) : broker(b) {
		if (broker) broker->enterBusy(reason);
	}
	~BusyScope() { if (broker) broker->exitBusy(); }

private:
	BusyScope(const BusyScope&);
	BusyScope& operator=(const BusyScope&);
};

HttpResult DzScriptServerPane::handleSaveCopy(const QByteArray& jsonBody)
{
	// ── Parse ─────────────────────────────────────────────────────────────────
	QVariantMap body;
	std::string parseErrDetail;
	if (!JsonStd::parseObject(jsonBody, body, parseErrDetail)) {
		return HttpResult(400, stdToQBA(
			ErrorResponse::build(ErrorCode::INVALID_JSON, parseErrDetail)));
	}

	QString destPath = body.value("path").toString().trimmed();

	if (destPath.isEmpty()) {
		return HttpResult(400, stdToQBA(
			ErrorResponse::build(ErrorCode::MISSING_FIELD, "path")));
	}

	if (!dzScene) {
		return HttpResult(500, stdToQBA(
			ErrorResponse::build(ErrorCode::INTERNAL_ERROR, "dzScene is null")));
	}

	// ── Snapshot current state ────────────────────────────────────────────────
	QString origFilename = dzScene->getFilename();
	bool    wasDirty     = dzScene->needsSave();

	// Neither branch below is guaranteed to be bracketed by DzScene's own
	// sceneSaveStarting/sceneSaved signals (Case 1's QFile::copy never calls
	// DzScene::saveScene() at all), so track busy state explicitly here rather
	// than relying solely on signal-driven detection. See daz-script-server-aaa.
	BusyScope busyGuard(m_pEventBroker, MainThreadBusy::SceneSaving);

	// ── Case 1: clean scene with a saved file — skip serialisation entirely ──
	// QFile::copy does not touch DAZ Studio scene state at all.
	if (!wasDirty && !origFilename.isEmpty() && QFile::exists(origFilename)) {
		if (QFile::exists(destPath))
			QFile::remove(destPath);
		if (!QFile::copy(origFilename, destPath)) {
			return HttpResult(500, stdToQBA(
				ErrorResponse::build(ErrorCode::INTERNAL_ERROR, "file copy failed")));
		}
		JsonBuilder jb;
		jb.startObject();
		jb.addMember("ok",     true);
		jb.addMember("path",   destPath);
		jb.addMember("source", origFilename);
		jb.addMember("method", "copy");
		jb.finishObject();
		return HttpResult(200, jb.toString().toUtf8());
	}

	// ── Case 2: scene needs serialisation ────────────────────────────────────
	// saveScene() serialises the current in-memory state to destPath.
	// If it also updates the scene's internal filename pointer we restore it
	// immediately with a second saveScene() call.  A double-write is the only
	// available option when the scene has unsaved changes: doSave(saveOnly=true)
	// is compiled out in all current DAZ Studio 4.x DSON_IO builds.
	DzError err = dzScene->saveScene(destPath);
	if (err != DZ_NO_ERROR) {
		return HttpResult(500, stdToQBA(
			ErrorResponse::build(ErrorCode::INTERNAL_ERROR,
				"saveScene failed (code " + std::to_string((int)err) + ")")));
	}

	std::string method = "serialize";

	// Restore internal filename if saveScene changed it
	if (dzScene->getFilename() != origFilename) {
		method = "serialize+restore";
		if (!origFilename.isEmpty()) {
			// Note: this writes the original file again as a side effect.
			// When the scene has unsaved changes this also saves them to the
			// original file — there is no way to avoid this without the
			// (unavailable) doSave(saveOnly=true) API.
			dzScene->saveScene(origFilename);
		}
	}

	// Restore dirty flag
	if (wasDirty)
		dzScene->markChanged();

	JsonBuilder jb;
	jb.startObject();
	jb.addMember("ok",     true);
	jb.addMember("path",   destPath);
	jb.addMember("source", origFilename);
	jb.addMember("method", QString::fromStdString(method));
	jb.finishObject();
	return HttpResult(200, jb.toString().toUtf8());
}

#include "moc_DzScriptServerPane.cpp"
