// Include httplib ONLY here — it pulls in winsock2.h and Windows macros.
// CPPHTTPLIB_NO_COMPRESS is set via target_compile_definitions in CMakeLists.txt.
#include "httplib.h"

#include "DzScriptServerPane.h"
#include "SecureRandom.h"
#include "JsonBuilder.h"

#include <dzapp.h>
#include <dzscript.h>

#include <QtCore/qmetaobject.h>
#include <QtCore/qsettings.h>
#include <QtCore/qfile.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qdir.h>
#include <QtCore/qtextstream.h>
#include <QtCore/qfileinfo.h>
#include <QtCore/qcryptographichash.h>
#include <QtCore/quuid.h>
#include <QtCore/qmutexlocker.h>
#include <QtGui/qboxlayout.h>
#include <QtGui/qformlayout.h>
#include <QtGui/qgroupbox.h>
#include <QtGui/qclipboard.h>
#include <QtGui/qapplication.h>
#include <QtGui/qmessagebox.h>
#include <QtScript/qscriptengine.h>
#include <QtScript/qscriptvalue.h>

// Platform-specific includes for file permissions
#ifndef _WIN32
	#include <sys/stat.h>  // chmod, S_IRUSR, S_IWUSR
#endif

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
	, m_nPort(18811)
	, m_sHost("127.0.0.1")
	, m_bRunning(false)
	, m_bCapturingLog(false)
	, m_nTimeoutSec(30)
	, m_bAuthEnabled(true)
	, m_nActiveRequests(0)
{
	// Load settings and token
	loadSettings();
	loadOrGenerateToken();

	// ── Build UI ─────────────────────────────────────────────────────────────
	QFormLayout* formLayout = new QFormLayout();
	formLayout->setContentsMargins(6, 6, 6, 6);

	m_pHostEdit = new QLineEdit(m_sHost, this);
	formLayout->addRow(tr("Host:"), m_pHostEdit);

	m_pPortSpin = new QSpinBox(this);
	m_pPortSpin->setRange(1024, 65535);
	m_pPortSpin->setValue(m_nPort);
	formLayout->addRow(tr("Port:"), m_pPortSpin);

	m_pTimeoutSpin = new QSpinBox(this);
	m_pTimeoutSpin->setRange(5, 300);
	m_pTimeoutSpin->setSuffix(tr(" sec"));
	m_pTimeoutSpin->setValue(m_nTimeoutSec);
	formLayout->addRow(tr("Timeout:"), m_pTimeoutSpin);

	// Authentication section
	QGroupBox* authGroup = new QGroupBox(tr("Authentication"), this);
	QVBoxLayout* authLayout = new QVBoxLayout(authGroup);

	m_pAuthEnabledCheck = new QCheckBox(tr("Enable API Token Authentication"), this);
	m_pAuthEnabledCheck->setChecked(m_bAuthEnabled);
	authLayout->addWidget(m_pAuthEnabledCheck);

	QHBoxLayout* tokenLayout = new QHBoxLayout();
	QLabel* tokenLabel = new QLabel(tr("API Token:"), this);
	tokenLayout->addWidget(tokenLabel);

	m_pTokenEdit = new QLineEdit(this);
	m_pTokenEdit->setText(m_sApiToken);
	m_pTokenEdit->setReadOnly(true);
	m_pTokenEdit->setEchoMode(QLineEdit::Password);
	tokenLayout->addWidget(m_pTokenEdit);

	m_pCopyTokenBtn = new QPushButton(tr("Copy"), this);
	m_pCopyTokenBtn->setMaximumWidth(60);
	tokenLayout->addWidget(m_pCopyTokenBtn);

	m_pRegenTokenBtn = new QPushButton(tr("Regenerate"), this);
	m_pRegenTokenBtn->setMaximumWidth(90);
	tokenLayout->addWidget(m_pRegenTokenBtn);

	authLayout->addLayout(tokenLayout);

	QLabel* authHint = new QLabel(
		tr("Clients must send token via 'X-API-Token' header"), this);
	authHint->setStyleSheet("QLabel { color: gray; font-size: 9pt; }");
	authLayout->addWidget(authHint);

	m_pStatusLabel = new QLabel(tr("Stopped"), this);

	m_pStartBtn = new QPushButton(tr("Start Server"), this);
	m_pStopBtn  = new QPushButton(tr("Stop Server"),  this);
	m_pStopBtn->setEnabled(false);

	QHBoxLayout* btnLayout = new QHBoxLayout();
	btnLayout->addWidget(m_pStartBtn);
	btnLayout->addWidget(m_pStopBtn);

	QHBoxLayout* logHeaderLayout = new QHBoxLayout();
	QLabel* logLabel = new QLabel(tr("Request Log:"), this);
	logHeaderLayout->addWidget(logLabel);
	logHeaderLayout->addStretch();
	m_pClearLogBtn = new QPushButton(tr("Clear Log"), this);
	m_pClearLogBtn->setMaximumWidth(80);
	logHeaderLayout->addWidget(m_pClearLogBtn);

	m_pLogView = new QTextEdit(this);
	m_pLogView->setReadOnly(true);
	m_pLogView->setMaximumHeight(120);

	QVBoxLayout* mainLayout = new QVBoxLayout(this);
	mainLayout->setContentsMargins(4, 4, 4, 4);
	mainLayout->addLayout(formLayout);
	mainLayout->addWidget(authGroup);
	mainLayout->addWidget(m_pStatusLabel);
	mainLayout->addLayout(btnLayout);
	mainLayout->addLayout(logHeaderLayout);
	mainLayout->addWidget(m_pLogView);
	mainLayout->addStretch();
	setLayout(mainLayout);

	connect(m_pStartBtn, SIGNAL(clicked()), this, SLOT(onStartClicked()));
	connect(m_pStopBtn,  SIGNAL(clicked()), this, SLOT(onStopClicked()));
	connect(m_pCopyTokenBtn, SIGNAL(clicked()), this, SLOT(onCopyTokenClicked()));
	connect(m_pRegenTokenBtn, SIGNAL(clicked()), this, SLOT(onRegenTokenClicked()));
	connect(m_pAuthEnabledCheck, SIGNAL(stateChanged(int)), this, SLOT(onAuthEnabledChanged(int)));
	connect(m_pClearLogBtn, SIGNAL(clicked()), this, SLOT(onClearLogClicked()));

	updateUI();
}

DzScriptServerPane::~DzScriptServerPane()
{
	stopServer();
	saveSettings();
}

// ─── Start / Stop ─────────────────────────────────────────────────────────────

void DzScriptServerPane::onStartClicked()
{
	m_nPort = m_pPortSpin->value();
	m_sHost = m_pHostEdit->text();
	m_nTimeoutSec = m_pTimeoutSpin->value();
	saveSettings();
	startServer();
}

void DzScriptServerPane::onStopClicked()
{
	stopServer();
}

void DzScriptServerPane::startServer()
{
	if (m_bRunning)
		return;

	// Verify we have a valid API token before starting
	if (m_bAuthEnabled && (m_sApiToken.isEmpty() || m_sApiToken.length() < 32)) {
		appendLog("[ERROR] Cannot start server: No valid API token available");
		QMessageBox::critical(this, tr("Security Error"),
			tr("Cannot start server without a valid API token.\n\n"
			   "Token generation may have failed. Check the log for details."));
		return;
	}

	m_pServer = new httplib::Server();
	m_pServer->set_read_timeout(m_nTimeoutSec, 0);

	// Limit concurrent connections to prevent resource exhaustion
	// cpp-httplib spawns a thread per request; limit keep-alive to reduce thread buildup
	m_pServer->set_keep_alive_max_count(5);  // Max 5 requests per persistent connection
	m_pServer->set_keep_alive_timeout(5);     // 5 second keep-alive timeout

	// Set socket flags to improve resource handling
	m_pServer->set_socket_options([](int sock) {
		// Enable address reuse to prevent "address already in use" errors
		int yes = 1;
#ifdef _WIN32
		setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, (char*)&yes, sizeof(yes));
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
		appendLog(QString("[ERROR] Failed to initialize server"));
		delete m_pServer;
		m_pServer = nullptr;
		delete m_pServerThread;
		m_pServerThread = nullptr;
		return;
	}

	m_pServerThread->start();

	// Give thread a moment to bind
	ServerListenThread::msSleep(100);

	// Check if server bound successfully
	if (!m_pServer->is_running()) {
		appendLog(QString("[ERROR] Failed to bind to %1:%2 - port may be in use")
			.arg(m_sHost).arg(m_nPort));
		delete m_pServer;
		m_pServer = nullptr;
		if (m_pServerThread) {
			m_pServerThread->wait(1000);
			delete m_pServerThread;
			m_pServerThread = nullptr;
		}
		return;
	}

	m_bRunning = true;
	updateUI();
	appendLog(QString("[%1] Server started on %2:%3 (timeout: %4s)")
		.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
		.arg(m_sHost)
		.arg(m_nPort)
		.arg(m_nTimeoutSec));
}

void DzScriptServerPane::stopServer()
{
	if (!m_bRunning)
		return;

	if (m_pServer) {
		m_pServer->stop();
		delete m_pServer;  // FIX: Delete server object to prevent memory leak
		m_pServer = nullptr;
	}
	if (m_pServerThread) {
		if (!m_pServerThread->wait(5000)) {
			appendLog("Warning: Server thread did not stop cleanly");
		}
		delete m_pServerThread;
		m_pServerThread = nullptr;
	}

	m_bRunning = false;
	updateUI();
	appendLog("Server stopped.");
}

void DzScriptServerPane::updateUI()
{
	if (m_bRunning) {
		QString authStatus = m_bAuthEnabled ? tr("Protected") : tr("⚠ Unprotected");
		m_pStatusLabel->setText(tr("Running on %1:%2 (%3)")
			.arg(m_sHost).arg(m_nPort).arg(authStatus));
		m_pStartBtn->setEnabled(false);
		m_pStopBtn->setEnabled(true);
		m_pHostEdit->setEnabled(false);
		m_pPortSpin->setEnabled(false);
		m_pTimeoutSpin->setEnabled(false);
		m_pAuthEnabledCheck->setEnabled(false);
		m_pRegenTokenBtn->setEnabled(false);
	} else {
		m_pStatusLabel->setText(tr("Stopped"));
		m_pStartBtn->setEnabled(true);
		m_pStopBtn->setEnabled(false);
		m_pHostEdit->setEnabled(true);
		m_pPortSpin->setEnabled(true);
		m_pTimeoutSpin->setEnabled(true);
		m_pAuthEnabledCheck->setEnabled(true);
		m_pRegenTokenBtn->setEnabled(true);
	}
}

void DzScriptServerPane::appendLog(const QString& line)
{
	if (!m_pLogView)
		return;

	m_pLogView->append(line);

	// Limit log view to prevent unbounded memory growth
	QTextDocument* doc = m_pLogView->document();
	if (doc && doc->blockCount() > ServerConfig::MAX_LOG_LINES) {
		// Remove oldest lines
		QTextCursor cursor(doc);
		cursor.movePosition(QTextCursor::Start);
		cursor.movePosition(QTextCursor::Down, QTextCursor::KeepAnchor,
		                    doc->blockCount() - ServerConfig::MAX_LOG_LINES);
		cursor.removeSelectedText();
		cursor.deleteChar();  // Remove the newline after selection
	}
}

// ─── Route setup ──────────────────────────────────────────────────────────────
//
// THREADING RULE: httplib invokes these handlers on raw std::threads (not QThreads).
// Handlers must do NO Qt work beyond constructing/copying QByteArray.
// All Qt work happens in handleExecuteRequest() on the main thread via
// Qt::BlockingQueuedConnection.

void DzScriptServerPane::setupRoutes()
{
	// ─── GET /status ──────────────────────────────────────────────────────────
	m_pServer->Get("/status", [](const httplib::Request&, httplib::Response& res) {
		res.set_content("{\"running\":true,\"version\":\"1.1.0\"}",
		                "application/json");
	});

	// ─── GET /health ──────────────────────────────────────────────────────────
	m_pServer->Get("/health", [this](const httplib::Request&, httplib::Response& res) {
		QString json = getHealthJson();
		QByteArray jsonBytes = json.toUtf8();
		res.set_content(jsonBytes.constData(), jsonBytes.size(), "application/json");
	});

	// ─── GET /metrics ─────────────────────────────────────────────────────────
	m_pServer->Get("/metrics", [this](const httplib::Request&, httplib::Response& res) {
		QString json = getMetricsJson();
		QByteArray jsonBytes = json.toUtf8();
		res.set_content(jsonBytes.constData(), jsonBytes.size(), "application/json");
	});

	// ─── POST /execute ────────────────────────────────────────────────────────
	m_pServer->Post("/execute", [this](const httplib::Request& req, httplib::Response& res) {
		// Check concurrent request limit (DoS protection)
		if (m_nActiveRequests >= ServerConfig::MAX_CONCURRENT_REQUESTS) {
			res.status = 429;  // Too Many Requests
			res.set_content(
				"{\"success\":false,\"error\":\"Server busy - too many concurrent requests\"}",
				"application/json");
			return;
		}

		// Increment active request counter
		m_nActiveRequests++;

		// Get client IP for logging
		std::string clientIP = req.remote_addr.empty() ? "unknown" : req.remote_addr;

		// Body size validation
		if (req.body.size() > ServerConfig::MAX_BODY_SIZE) {
			m_nActiveRequests--;  // Decrement before returning
			res.status = 413;  // Payload Too Large
			res.set_content(
				"{\"success\":false,\"error\":\"Request body too large (max 5MB)\"}",
				"application/json");
			return;
		}

		// Authentication check
		if (m_bAuthEnabled) {
			std::string authHeader = req.get_header_value("X-API-Token");
			if (authHeader.empty()) {
				// Also check Authorization: Bearer <token>
				authHeader = req.get_header_value("Authorization");
				if (authHeader.find("Bearer ") == 0) {
					authHeader = authHeader.substr(7);  // Remove "Bearer " prefix
				}
			}

			if (!validateToken(authHeader)) {
				m_nActiveRequests--;  // Decrement before returning
				res.status = 401;
				res.set_content(
					"{\"success\":false,\"error\":\"Unauthorized: Invalid or missing API token\"}",
					"application/json");

				// Record auth failure
				{
					QMutexLocker lock(&m_metrics.mutex);
					m_metrics.authFailures++;
				}

				// Log failed auth attempt
				QString logMsg = QString("[%1] [AUTH FAILED] %2")
					.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
					.arg(QString::fromStdString(clientIP));
				QMetaObject::invokeMethod(this, "appendLog", Qt::QueuedConnection,
					Q_ARG(QString, logMsg));
				return;
			}
		}

		QByteArray bodyBytes(req.body.c_str(), (int)req.body.size());
		QByteArray clientIPBytes(clientIP.c_str(), (int)clientIP.size());
		QByteArray responseBytes;

		QMetaObject::invokeMethod(
			this, "handleExecuteRequest",
			Qt::BlockingQueuedConnection,
			Q_RETURN_ARG(QByteArray, responseBytes),
			Q_ARG(QByteArray, bodyBytes),
			Q_ARG(QByteArray, clientIPBytes));

		// Decrement active request counter
		m_nActiveRequests--;

		res.set_content(responseBytes.constData(), responseBytes.size(),
		                "application/json");
	});
}

// ─── Main-thread request handler ──────────────────────────────────────────────

QByteArray DzScriptServerPane::handleExecuteRequest(const QByteArray& jsonBody, const QByteArray& clientIP)
{
	QTime startTime = QTime::currentTime();
	QString clientIPStr = QString::fromUtf8(clientIP.constData(), clientIP.size());
	QString requestId = generateRequestId();

	// Parse JSON body (QScriptEngine is a QObject — only safe on a Qt-managed thread)
	QString bodyStr = QString::fromUtf8(jsonBody.constData(), jsonBody.size());

	// Error handling for malformed JSON
	QScriptEngine parseEngine;
	QScriptValue parsed = parseEngine.evaluate("(" + bodyStr + ")");
	if (parseEngine.hasUncaughtException()) {
		QString errorMsg = QString("Invalid JSON: %1 at line %2")
			.arg(parseEngine.uncaughtException().toString())
			.arg(parseEngine.uncaughtExceptionLineNumber());
		QString resp = buildResponseJson(false, QVariant(), QStringList(),
		                                 QVariant(errorMsg), requestId);
		appendLog(QString("[%1] [%2] [ERR] [0ms] [%3] JSON parse error")
			.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
			.arg(clientIPStr)
			.arg(requestId));
		recordRequest(false, 0);
		return resp.toUtf8();
	}

	QVariantMap bodyMap = parsed.toVariant().toMap();

	QString scriptFile = bodyMap.value("scriptFile").toString();
	QString scriptText = bodyMap.value("script").toString();
	QVariantMap argsMap = bodyMap.value("args").toMap();

	// Input validation
	if (scriptFile.isEmpty() && scriptText.isEmpty()) {
		QString resp = buildResponseJson(false, QVariant(), QStringList(),
		                                 QVariant(QString("Request must include either 'scriptFile' (path) or 'script' (inline code) field")),
		                                 requestId);
		appendLog(QString("[%1] [%2] [ERR] [0ms] [%3] Missing script/scriptFile")
			.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
			.arg(clientIPStr)
			.arg(requestId));
		recordRequest(false, 0);
		return resp.toUtf8();
	}

	// Warn if both are provided
	if (!scriptFile.isEmpty() && !scriptText.isEmpty()) {
		appendLog(QString("[%1] [%2] [WARN] [%3] Both scriptFile and script provided, using scriptFile")
			.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
			.arg(clientIPStr)
			.arg(requestId));
	}

	// Validate script text length (use config constant)
	if (!scriptText.isEmpty() && scriptText.length() > ServerConfig::MAX_SCRIPT_LENGTH) {
		QString resp = buildResponseJson(false, QVariant(), QStringList(),
		                                 QVariant(QString("Script text too large (max 1MB)")),
		                                 requestId);
		appendLog(QString("[%1] [%2] [ERR] [0ms] [%3] Script too large (%4 bytes)")
			.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
			.arg(clientIPStr)
			.arg(requestId)
			.arg(scriptText.length()));
		recordRequest(false, 0);
		return resp.toUtf8();
	}

	// Validate scriptFile path
	if (!scriptFile.isEmpty()) {
		QFileInfo fileInfo(scriptFile);
		if (!fileInfo.exists()) {
			QString resp = buildResponseJson(false, QVariant(), QStringList(),
			                                 QVariant(QString("Script file not found: %1").arg(scriptFile)),
			                                 requestId);
			appendLog(QString("[%1] [%2] [ERR] [0ms] [%3] File not found: %4")
				.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
				.arg(clientIPStr)
				.arg(requestId)
				.arg(scriptFile));
			recordRequest(false, 0);
			return resp.toUtf8();
		}
		if (!fileInfo.isFile()) {
			QString resp = buildResponseJson(false, QVariant(), QStringList(),
			                                 QVariant(QString("Path is not a file: %1").arg(scriptFile)),
			                                 requestId);
			appendLog(QString("[%1] [%2] [ERR] [0ms] [%3] Not a file: %4")
				.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
				.arg(clientIPStr)
				.arg(requestId)
				.arg(scriptFile));
			recordRequest(false, 0);
			return resp.toUtf8();
		}
		if (!fileInfo.isAbsolute()) {
			QString resp = buildResponseJson(false, QVariant(), QStringList(),
			                                 QVariant(QString("Script file path must be absolute: %1").arg(scriptFile)),
			                                 requestId);
			appendLog(QString("[%1] [%2] [ERR] [0ms] [%3] Path not absolute: %4")
				.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
				.arg(clientIPStr)
				.arg(requestId)
				.arg(scriptFile));
			recordRequest(false, 0);
			return resp.toUtf8();
		}
	}

	// Capture dzApp debug output (print() in DazScript)
	m_aCapturedLogLines.clear();
	m_bCapturingLog = true;
	connect(dzApp, SIGNAL(debugMsg(const QString&)),
	        this,  SLOT(onMessagePosted(const QString&)),
	        Qt::DirectConnection);

	DzScript* script = new DzScript();

	if (!scriptFile.isEmpty()) {
		// loadFromFile sets the filename so getScriptFileName() and relative
		// include() calls work correctly inside the script.
		if (!script->loadFromFile(scriptFile)) {
			delete script;
			disconnect(dzApp, SIGNAL(debugMsg(const QString&)),
			           this,  SLOT(onMessagePosted(const QString&)));
			m_bCapturingLog = false;
			QString resp = buildResponseJson(false, QVariant(), QStringList(),
			                                 QVariant(QString("Failed to load scriptFile: %1").arg(scriptFile)),
			                                 requestId);
			recordRequest(false, 0);
			return resp.toUtf8();
		}
	} else {
		script->setCode(scriptText);
	}

	// Args are passed via execute() and accessible in scripts via getArguments()[0],
	// since DzScriptContext methods are available as globals in every DzScript.
	QVariantList execArgs;
	execArgs << QVariant(argsMap);

QVariant scriptResult;
	QVariant errorVar;
	bool     success = true;

	bool executed = script->execute(execArgs);
	if (executed) {
		scriptResult = script->result();
	} else {
		success = false;
		QString errMsg  = script->errorMessage();
		int     errLine = script->errorLine();
		if (errLine > 0)
			errMsg = QString("Line %1: %2").arg(errLine).arg(errMsg);
		errorVar = QVariant(errMsg);
	}

	delete script;

	disconnect(dzApp, SIGNAL(debugMsg(const QString&)),
	           this,  SLOT(onMessagePosted(const QString&)));
	m_bCapturingLog = false;

	// Calculate execution duration
	int durationMs = startTime.msecsTo(QTime::currentTime());

	// Record metrics
	recordRequest(success, durationMs);

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

	QString resp = buildResponseJson(success,
	                                 success ? scriptResult : QVariant(),
	                                 m_aCapturedLogLines,
	                                 errorVar,
	                                 requestId);
	return resp.toUtf8();
}

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
}

// ─── JSON helpers (main thread only) ─────────────────────────────────────────

QString DzScriptServerPane::variantToJson(const QVariant& v)
{
	if (!v.isValid() || v.isNull())
		return "null";

	switch (v.type()) {
	case QVariant::Bool:
		return v.toBool() ? "true" : "false";
	case QVariant::Int:
	case QVariant::LongLong:
	case QVariant::UInt:
	case QVariant::ULongLong:
		return QString::number(v.toLongLong());
	case QVariant::Double:
		return QString::number(v.toDouble(), 'g', 15);
	case QVariant::String: {
		QString s = v.toString();
		s.replace('\\', "\\\\");
		s.replace('"',  "\\\"");
		s.replace('\n', "\\n");
		s.replace('\r', "\\r");
		s.replace('\t', "\\t");
		return "\"" + s + "\"";
	}
	case QVariant::List:
	case QVariant::StringList: {
		QVariantList list = v.toList();
		QStringList parts;
		foreach (const QVariant& item, list)
			parts.append(variantToJson(item));
		return "[" + parts.join(",") + "]";
	}
	case QVariant::Map: {
		QVariantMap map = v.toMap();
		QStringList parts;
		for (QVariantMap::const_iterator it = map.begin(); it != map.end(); ++it) {
			QString key = it.key();
			key.replace('\\', "\\\\");
			key.replace('"',  "\\\"");
			parts.append("\"" + key + "\":" + variantToJson(it.value()));
		}
		return "{" + parts.join(",") + "}";
	}
	default:
		return variantToJson(QVariant(v.toString()));
	}
}

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
	foreach (const QString& line, output)
		outputList.append(QVariant(line));
	json.addMember("output", QVariant(outputList));

	json.addMember("error", error);

	// Add request ID if provided (for debugging/correlation)
	if (!requestId.isEmpty()) {
		json.addMember("request_id", requestId);
	}

	json.finishObject();
	return json.toString();
}

// ─── Authentication ───────────────────────────────────────────────────────────

QString DzScriptServerPane::generateToken()
{
	// Generate cryptographically secure 128-bit token using platform crypto APIs
	// Windows: CryptoAPI (CryptGenRandom)
	// Unix/macOS: /dev/urandom
	QString token = SecureRandom::generateHexToken(16);  // 16 bytes = 128 bits = 32 hex chars

	if (token.isEmpty()) {
		// CRITICAL: Crypto API failed - cannot generate secure token
		appendLog("[ERROR] Failed to generate secure token - crypto API unavailable");
		return QString();
	}

	return token;
}

QString getTokenFilePath()
{
	QString homeDir = QDir::homePath();
	QString dazDir = homeDir + "/.daz3d";

	// Create directory if it doesn't exist
	QDir dir;
	if (!dir.exists(dazDir)) {
		dir.mkpath(dazDir);
	}

	return dazDir + "/dazscriptserver_token.txt";
}

void DzScriptServerPane::loadOrGenerateToken()
{
	QString tokenPath = getTokenFilePath();
	QFile file(tokenPath);

	if (file.exists()) {
#ifndef _WIN32
		// Unix/macOS: Check file permissions for security
		QFileInfo info(tokenPath);
		QFile::Permissions perms = info.permissions();
		if (perms & (QFile::ReadGroup | QFile::WriteGroup |
		             QFile::ReadOther | QFile::WriteOther)) {
			appendLog(QString("[WARN] Token file has insecure permissions - "
			                  "others can read it! File: %1").arg(tokenPath));
			appendLog(QString("[WARN] Run: chmod 600 %1").arg(tokenPath));
		}
#endif

		if (file.open(QIODevice::ReadOnly | QIODevice::Text)) {
			QTextStream in(&file);
			m_sApiToken = in.readLine().trimmed();
			file.close();

			if (m_sApiToken.isEmpty() || m_sApiToken.length() < 32) {
				// Invalid token, generate new one
				appendLog("[INFO] Existing token invalid, generating new one");
				m_sApiToken = generateToken();
				if (m_sApiToken.isEmpty()) {
					// CRITICAL: Cannot generate secure token
					QMessageBox::critical(this, tr("Security Error"),
						tr("Failed to generate secure API token.\n\n"
						   "The cryptographic API is unavailable on this system.\n"
						   "The plugin cannot start safely without a secure token."));
					return;
				}
				saveToken();
			}
			return;  // Successfully loaded or regenerated token
		}
	}

	// No token file exists, generate new one
	appendLog("[INFO] No token file found, generating new secure token");
	m_sApiToken = generateToken();
	if (m_sApiToken.isEmpty()) {
		// CRITICAL: Cannot generate secure token
		QMessageBox::critical(this, tr("Security Error"),
			tr("Failed to generate secure API token.\n\n"
			   "The cryptographic API is unavailable on this system.\n"
			   "The plugin cannot start safely without a secure token."));
		return;
	}
	saveToken();
	appendLog(QString("Generated new API token: %1").arg(tokenPath));
}

void DzScriptServerPane::saveToken()
{
	QString tokenPath = getTokenFilePath();
	QFile file(tokenPath);

	if (file.open(QIODevice::WriteOnly | QIODevice::Text)) {
		QTextStream out(&file);
		out << m_sApiToken << "\n";
		file.close();

#ifndef _WIN32
		// Unix/macOS: Set restrictive permissions (owner read/write only, 0600)
		if (chmod(tokenPath.toUtf8().constData(), S_IRUSR | S_IWUSR) != 0) {
			appendLog(QString("[WARN] Failed to set restrictive permissions on %1")
				.arg(tokenPath));
		}
#else
		// Windows: Setting proper ACLs requires Windows security APIs
		// For now, warn the user to manually restrict access
		appendLog(QString("[INFO] Token saved to %1").arg(tokenPath));
		appendLog(QString("[WARN] On Windows, manually restrict access to this file to your user account only"));
#endif
	} else {
		appendLog(QString("[ERROR] Failed to save token to %1").arg(tokenPath));
	}
}

void DzScriptServerPane::loadSettings()
{
	QSettings settings("DAZ 3D", "DazScriptServer");
	m_sHost = settings.value("host", "127.0.0.1").toString();
	m_nPort = settings.value("port", 18811).toInt();
	m_nTimeoutSec = settings.value("timeout", 30).toInt();
	m_bAuthEnabled = settings.value("authEnabled", true).toBool();
}

void DzScriptServerPane::saveSettings()
{
	QSettings settings("DAZ 3D", "DazScriptServer");
	settings.setValue("host", m_sHost);
	settings.setValue("port", m_nPort);
	settings.setValue("timeout", m_nTimeoutSec);
	settings.setValue("authEnabled", m_bAuthEnabled);
}

bool DzScriptServerPane::validateToken(const std::string& providedToken) const
{
	if (providedToken.empty())
		return false;

	QString providedTokenQt = QString::fromStdString(providedToken).trimmed();
	return providedTokenQt == m_sApiToken;
}

void DzScriptServerPane::onCopyTokenClicked()
{
	QClipboard* clipboard = QApplication::clipboard();
	if (clipboard) {
		clipboard->setText(m_sApiToken);
		appendLog("API token copied to clipboard");
	}
}

void DzScriptServerPane::onRegenTokenClicked()
{
	QMessageBox msgBox;
	msgBox.setWindowTitle(tr("Regenerate Token"));
	msgBox.setText(tr("This will generate a new API token and invalidate the old one."));
	msgBox.setInformativeText(tr("All clients will need to be updated with the new token. Continue?"));
	msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
	msgBox.setDefaultButton(QMessageBox::No);

	if (msgBox.exec() == QMessageBox::Yes) {
		m_sApiToken = generateToken();
		m_pTokenEdit->setText(m_sApiToken);
		saveToken();
		appendLog("New API token generated");
	}
}

void DzScriptServerPane::onAuthEnabledChanged(int state)
{
	m_bAuthEnabled = (state == Qt::Checked);
	saveSettings();

	if (!m_bAuthEnabled && m_bRunning) {
		appendLog("[WARN] Authentication disabled - anyone can execute scripts!");
	}
}

void DzScriptServerPane::onClearLogClicked()
{
	if (m_pLogView) {
		m_pLogView->clear();
	}
}

// ─── Metrics and Monitoring ───────────────────────────────────────────────────

QString DzScriptServerPane::generateRequestId()
{
	// Generate unique request ID using UUID (shortened to 8 chars for logs)
	QUuid uuid = QUuid::createUuid();
	QString fullId = uuid.toString();
	// Remove braces and take first 8 characters: "{xxxxxxxx-...}" -> "xxxxxxxx"
	return fullId.mid(1, 8);
}

void DzScriptServerPane::recordRequest(bool success, qint64 durationMs)
{
	QMutexLocker lock(&m_metrics.mutex);
	m_metrics.totalRequests++;
	if (success) {
		m_metrics.successfulRequests++;
	} else {
		m_metrics.failedRequests++;
	}
	Q_UNUSED(durationMs);  // Could track duration histogram here
}

QString DzScriptServerPane::getHealthJson() const
{
	QMutexLocker lock(&m_metrics.mutex);

	JsonBuilder json;
	json.startObject();
	json.addMember("status", "ok");
	json.addMember("version", "1.1.0");
	json.addMember("running", m_bRunning);
	json.addMember("auth_enabled", m_bAuthEnabled);
	json.addMember("active_requests", m_nActiveRequests);

	qint64 uptimeSecs = m_metrics.startTime.secsTo(QDateTime::currentDateTime());
	json.addMember("uptime_seconds", uptimeSecs);

	json.finishObject();
	return json.toString();
}

QString DzScriptServerPane::getMetricsJson() const
{
	QMutexLocker lock(&m_metrics.mutex);

	JsonBuilder json;
	json.startObject();

	json.addMember("total_requests", m_metrics.totalRequests);
	json.addMember("successful_requests", m_metrics.successfulRequests);
	json.addMember("failed_requests", m_metrics.failedRequests);
	json.addMember("auth_failures", m_metrics.authFailures);
	json.addMember("active_requests", m_nActiveRequests);

	qint64 uptimeSecs = m_metrics.startTime.secsTo(QDateTime::currentDateTime());
	json.addMember("uptime_seconds", uptimeSecs);

	// Calculate success rate
	if (m_metrics.totalRequests > 0) {
		double successRate = (double)m_metrics.successfulRequests / m_metrics.totalRequests * 100.0;
		json.addMember("success_rate_percent", successRate);
	} else {
		json.addMember("success_rate_percent", 0.0);
	}

	json.finishObject();
	return json.toString();
}

#include "moc_DzScriptServerPane.cpp"
