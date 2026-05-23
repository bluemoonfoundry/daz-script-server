// Include httplib ONLY here — it pulls in winsock2.h and Windows macros.
// CPPHTTPLIB_NO_COMPRESS is set via target_compile_definitions in CMakeLists.txt.
#include "httplib.h"
#include <ctime>
#include <vector>

#include "DzScriptServerPane.h"
#include "JsonBuilder.h"
#include "JsonStd.h"
#include "ErrorResponse.h"
#include "RequestValidator.h"
#include "common_version.h"

#include <dzapp.h>
#include <dzscript.h>
#include <dzrendermgr.h>
#include <dzrenderer.h>

#include <QtCore/qmetaobject.h>
#include <QtCore/qsettings.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qfile.h>
#include <QtCore/qfileinfo.h>
#include <QtCore/qregexp.h>
#include <QtCore/qmutex.h>
#include <QtCore/qscopedpointer.h>
#include <QtGui/qboxlayout.h>
#include <QtGui/qformlayout.h>
#include <QtGui/qgroupbox.h>
#include <QtGui/qclipboard.h>
#include <QtGui/qapplication.h>
#include <QtGui/qmessagebox.h>
#include <QtGui/qscrollarea.h>
#include <QtScript/qscriptengine.h>
#include <QtScript/qscriptvalue.h>

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
	, m_nActiveRequests(0)
	, m_bAutoStart(false)
	, m_nMaxConcurrentRequests(ServerConfig::DEFAULT_MAX_CONCURRENT_REQUESTS)
	, m_nMaxBodySizeMB(ServerConfig::DEFAULT_MAX_BODY_SIZE_MB)
	, m_nMaxScriptLengthKB(ServerConfig::DEFAULT_MAX_SCRIPT_LENGTH_KB)
	, m_rateLimiter(ServerConfig::DEFAULT_RATE_LIMIT_MAX, ServerConfig::DEFAULT_RATE_LIMIT_WINDOW)
	, m_pAsyncMgr(nullptr)
	, m_pCleanupTimer(nullptr)
	, m_pEventBroker(nullptr)
	, m_pRenderProgress(nullptr)
	, m_pEventClientsLabel(nullptr)
{
	// Register return type for BlockingQueuedConnection on execute/register handlers.
	qRegisterMetaType<HttpResult>("HttpResult");

	// Load settings and token
	loadSettings();

	QStringList tokenMsgs;
	if (!m_auth.loadOrGenerateToken(tokenMsgs)) {
		// Crypto API unavailable — log will be empty at this point, messages shown later
	}
	foreach (const QString& msg, tokenMsgs)
		appendLog(msg);

	// ── Async request manager ─────────────────────────────────────────────────
	// Pass 'this' so AsyncRequestManager can invoke processNextAsyncRequest()
	// and killRenderOnMainThread() via QMetaObject::invokeMethod internally.
	m_pAsyncMgr = new AsyncRequestManager(this);

	// ── Async cleanup timer ───────────────────────────────────────────────────
	// Created here so it lives on the main thread (correct for QTimer).
	// Started in startServer(), stopped in stopServer().
	m_pCleanupTimer = new QTimer(this);
	connect(m_pCleanupTimer, SIGNAL(timeout()), this, SLOT(cleanupExpiredRequests()));

	// ── Build UI ─────────────────────────────────────────────────────────────
	QLabel* titleLabel = new QLabel(
		QString("DAZ Script Server  v%1").arg(DZSRV_VERSION_STR), this);
	titleLabel->setStyleSheet(
		"QLabel { font-size: 11pt; font-weight: bold; padding: 4px 0px; }");
	titleLabel->setAlignment(Qt::AlignCenter);

	QFrame* titleSep = new QFrame(this);
	titleSep->setFrameShape(QFrame::HLine);
	titleSep->setFrameShadow(QFrame::Sunken);

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
	m_pAuthEnabledCheck->setChecked(m_auth.isEnabled());
	authLayout->addWidget(m_pAuthEnabledCheck);

	QHBoxLayout* tokenLayout = new QHBoxLayout();
	QLabel* tokenLabel = new QLabel(tr("API Token:"), this);
	tokenLayout->addWidget(tokenLabel);

	m_pTokenEdit = new QLineEdit(this);
	m_pTokenEdit->setText(m_auth.getToken());
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

	// ─── IP Whitelist ─────────────────────────────────────────────────────
	QGroupBox* whitelistGroup = new QGroupBox(tr("IP Whitelist"), this);
	QVBoxLayout* whitelistLayout = new QVBoxLayout(whitelistGroup);

	m_pIpWhitelistCheck = new QCheckBox(tr("Enable IP Whitelist (comma-separated)"), this);
	m_pIpWhitelistCheck->setChecked(m_ipWhitelist.isEnabled());
	whitelistLayout->addWidget(m_pIpWhitelistCheck);

	QHBoxLayout* whitelistInputLayout = new QHBoxLayout();
	QLabel* whitelistLabel = new QLabel(tr("Allowed IPs:"), this);
	whitelistInputLayout->addWidget(whitelistLabel);

	m_pIpWhitelistEdit = new QLineEdit(this);
	m_pIpWhitelistEdit->setText(m_ipWhitelist.getWhitelist());
	m_pIpWhitelistEdit->setPlaceholderText(tr("127.0.0.1, 192.168.1.100"));
	whitelistInputLayout->addWidget(m_pIpWhitelistEdit);
	whitelistLayout->addLayout(whitelistInputLayout);

	QLabel* whitelistHint = new QLabel(
		tr("Only requests from these IPs will be accepted (blocks others before authentication)"),
		this);
	whitelistHint->setStyleSheet("QLabel { color: gray; font-size: 9pt; }");
	whitelistLayout->addWidget(whitelistHint);

	// ─── Rate Limiting ────────────────────────────────────────────────────
	QGroupBox* rateLimitGroup = new QGroupBox(tr("Rate Limiting"), this);
	QVBoxLayout* rateLimitLayout = new QVBoxLayout(rateLimitGroup);

	m_pRateLimitCheck = new QCheckBox(tr("Enable Per-IP Rate Limiting"), this);
	m_pRateLimitCheck->setChecked(m_rateLimiter.isEnabled());
	rateLimitLayout->addWidget(m_pRateLimitCheck);

	QFormLayout* rateLimitFormLayout = new QFormLayout();

	m_pRateLimitMaxSpin = new QSpinBox(this);
	m_pRateLimitMaxSpin->setRange(10, 1000);
	m_pRateLimitMaxSpin->setValue(ServerConfig::DEFAULT_RATE_LIMIT_MAX);
	m_pRateLimitMaxSpin->setSuffix(tr(" requests"));
	rateLimitFormLayout->addRow(tr("Max Requests:"), m_pRateLimitMaxSpin);

	m_pRateLimitWindowSpin = new QSpinBox(this);
	m_pRateLimitWindowSpin->setRange(10, 300);
	m_pRateLimitWindowSpin->setValue(ServerConfig::DEFAULT_RATE_LIMIT_WINDOW);
	m_pRateLimitWindowSpin->setSuffix(tr(" sec"));
	rateLimitFormLayout->addRow(tr("Time Window:"), m_pRateLimitWindowSpin);

	rateLimitLayout->addLayout(rateLimitFormLayout);

	QLabel* rateLimitHint = new QLabel(
		tr("Limits requests per IP to prevent brute force attacks"), this);
	rateLimitHint->setStyleSheet("QLabel { color: gray; font-size: 9pt; }");
	rateLimitLayout->addWidget(rateLimitHint);

	// ─── Advanced Limits ──────────────────────────────────────────────────
	QGroupBox* limitsGroup = new QGroupBox(tr("Advanced Limits"), this);
	QFormLayout* limitsFormLayout = new QFormLayout(limitsGroup);

	m_pMaxConcurrentSpin = new QSpinBox(this);
	m_pMaxConcurrentSpin->setRange(5, 50);
	m_pMaxConcurrentSpin->setValue(m_nMaxConcurrentRequests);
	m_pMaxConcurrentSpin->setSuffix(tr(" concurrent"));
	limitsFormLayout->addRow(tr("Max Concurrent Requests:"), m_pMaxConcurrentSpin);

	m_pMaxBodySizeSpin = new QSpinBox(this);
	m_pMaxBodySizeSpin->setRange(1, 50);
	m_pMaxBodySizeSpin->setValue(m_nMaxBodySizeMB);
	m_pMaxBodySizeSpin->setSuffix(tr(" MB"));
	limitsFormLayout->addRow(tr("Max Request Body Size:"), m_pMaxBodySizeSpin);

	m_pMaxScriptLengthSpin = new QSpinBox(this);
	m_pMaxScriptLengthSpin->setRange(100, 10240);
	m_pMaxScriptLengthSpin->setValue(m_nMaxScriptLengthKB);
	m_pMaxScriptLengthSpin->setSuffix(tr(" KB"));
	limitsFormLayout->addRow(tr("Max Script Length:"), m_pMaxScriptLengthSpin);

	QLabel* limitsHint = new QLabel(
		tr("Resource limits for request processing (restart server to apply)"), this);
	limitsHint->setStyleSheet("QLabel { color: gray; font-size: 9pt; }");
	limitsFormLayout->addRow(limitsHint);

	m_pStatusLabel = new QLabel(tr("Stopped"), this);

	m_pActiveRequestsLabel = new QLabel(tr("Active Requests: 0"), this);
	m_pActiveRequestsLabel->setStyleSheet("QLabel { color: #0066cc; font-weight: bold; }");

	m_pEventClientsLabel = new QLabel(tr("Event Clients: 0"), this);
	m_pEventClientsLabel->setStyleSheet("QLabel { color: #0066cc; font-weight: bold; }");

	m_pStartBtn = new QPushButton(tr("Start Server"), this);
	m_pStopBtn  = new QPushButton(tr("Stop Server"),  this);
	m_pStopBtn->setEnabled(false);

	m_pAutoStartCheck = new QCheckBox(tr("Start server when pane opens"), this);
	m_pAutoStartCheck->setChecked(m_bAutoStart);

	QHBoxLayout* btnLayout = new QHBoxLayout();
	btnLayout->addWidget(m_pStartBtn);
	btnLayout->addWidget(m_pStopBtn);
	btnLayout->addStretch();
	btnLayout->addWidget(m_pAutoStartCheck);

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

	QWidget* contentWidget = new QWidget(this);
	QVBoxLayout* mainLayout = new QVBoxLayout(contentWidget);
	mainLayout->setContentsMargins(4, 4, 4, 4);
	mainLayout->addWidget(titleLabel);
	mainLayout->addWidget(titleSep);
	mainLayout->addLayout(formLayout);
	mainLayout->addWidget(authGroup);
	mainLayout->addWidget(whitelistGroup);
	mainLayout->addWidget(rateLimitGroup);
	mainLayout->addWidget(limitsGroup);
	mainLayout->addWidget(m_pStatusLabel);
	mainLayout->addWidget(m_pActiveRequestsLabel);
	mainLayout->addWidget(m_pEventClientsLabel);
	mainLayout->addLayout(btnLayout);
	mainLayout->addLayout(logHeaderLayout);
	mainLayout->addWidget(m_pLogView);
	mainLayout->addStretch();

	QScrollArea* scrollArea = new QScrollArea(this);
	scrollArea->setWidget(contentWidget);
	scrollArea->setWidgetResizable(true);
	scrollArea->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
	scrollArea->setFrameShape(QFrame::NoFrame);

	QVBoxLayout* outerLayout = new QVBoxLayout(this);
	outerLayout->setContentsMargins(0, 0, 0, 0);
	outerLayout->addWidget(scrollArea);
	setLayout(outerLayout);

	connect(m_pStartBtn, SIGNAL(clicked()), this, SLOT(onStartClicked()));
	connect(m_pStopBtn,  SIGNAL(clicked()), this, SLOT(onStopClicked()));
	connect(m_pCopyTokenBtn, SIGNAL(clicked()), this, SLOT(onCopyTokenClicked()));
	connect(m_pRegenTokenBtn, SIGNAL(clicked()), this, SLOT(onRegenTokenClicked()));
	connect(m_pAuthEnabledCheck, SIGNAL(stateChanged(int)), this, SLOT(onAuthEnabledChanged(int)));
	connect(m_pClearLogBtn, SIGNAL(clicked()), this, SLOT(onClearLogClicked()));
	connect(m_pIpWhitelistCheck, SIGNAL(stateChanged(int)), this, SLOT(onIpWhitelistEnabledChanged(int)));
	connect(m_pRateLimitCheck, SIGNAL(stateChanged(int)), this, SLOT(onRateLimitEnabledChanged(int)));
	connect(m_pAutoStartCheck, SIGNAL(stateChanged(int)), this, SLOT(onAutoStartChanged(int)));

	updateUI();

	// Auto-start server if enabled
	if (m_bAutoStart) {
		appendLog("[INFO] Auto-starting server...");
		startServer();
	}
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

	// Capture advanced limit settings
	m_nMaxConcurrentRequests = m_pMaxConcurrentSpin->value();
	m_nMaxBodySizeMB = m_pMaxBodySizeSpin->value();
	m_nMaxScriptLengthKB = m_pMaxScriptLengthSpin->value();

	// Capture IP whitelist settings
	m_ipWhitelist.setEnabled(m_pIpWhitelistCheck->isChecked());
	m_ipWhitelist.setWhitelist(m_pIpWhitelistEdit->text());

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
	if (m_bRunning)
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

	m_pServer = new httplib::Server();
	m_pServer->set_read_timeout(m_nTimeoutSec, 0);
	// SSE connections are long-lived; the write timeout must exceed the
	// content-provider pop timeout (3 s) plus some slack.  5 s is the httplib
	// default but we set it explicitly so the intent is clear.
	m_pServer->set_write_timeout(5, 0);

	// Limit concurrent connections to prevent resource exhaustion
	// cpp-httplib spawns a thread per request; limit keep-alive to reduce thread buildup
	m_pServer->set_keep_alive_max_count(ServerConfig::HTTP_KEEP_ALIVE_MAX_COUNT);
	m_pServer->set_keep_alive_timeout(ServerConfig::HTTP_KEEP_ALIVE_TIMEOUT_SEC);

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
		appendLog(QString("[ERROR] Failed to initialize server: Socket creation failed. Check system resources and network configuration."));
		delete m_pServer;
		m_pServer = nullptr;
		delete m_pServerThread;
		m_pServerThread = nullptr;
		return;
	}

	m_pServerThread->start();

	ServerListenThread::msSleep(ServerConfig::SERVER_BIND_WAIT_MS);

	// Check if server bound successfully
	if (!m_pServer->is_running()) {
		appendLog(QString("[ERROR] Failed to bind to %1:%2 - Port is already in use by another application. Try a different port or stop the conflicting service.")
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

	m_pEventBroker = new SceneEventBroker(this);
	m_pEventBroker->start();

	m_pRenderProgress = new RenderProgressBroker();

	updateUI();
	appendLog(QString("[%1] Server started on %2:%3 (timeout: %4s)")
		.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
		.arg(m_sHost)
		.arg(m_nPort)
		.arg(m_nTimeoutSec));

	m_pCleanupTimer->start(ServerConfig::ASYNC_CLEANUP_INTERVAL_MIN * 60 * 1000);
}

void DzScriptServerPane::stopServer()
{
	if (!m_bRunning)
		return;

	// Stop async cleanup timer
	m_pCleanupTimer->stop();

	// 1. Stop the event and progress brokers: unblocks all SSE pop() calls so
	//    content-provider callbacks drain quickly before the server is torn down.
	if (m_pRenderProgress) {
		m_pRenderProgress->stopAll();
	}
	if (m_pEventBroker) {
		m_pEventBroker->stop();
		// Do NOT delete yet — SSE resource-releaser lambdas still hold a
		// raw pointer to the broker (captured as `broker`).  We delete below,
		// after all handler threads have been joined.
	}

	// 2. Stop the HTTP server: sets is_shutting_down = true so the chunked
	//    write loops exit on their next iteration.
	if (m_pServer) {
		m_pServer->stop();
		delete m_pServer;
		m_pServer = nullptr;
	}

	// 3. Join the listen thread.  httplib's ThreadPool::shutdown() joins every
	//    request-handler thread before listen() returns, so by the time wait()
	//    completes ALL SSE resource-releaser lambdas have already run.
	if (m_pServerThread) {
		if (!m_pServerThread->wait(ServerConfig::SERVER_THREAD_STOP_TIMEOUT_MS)) {
			appendLog("[WARN] Server thread did not stop within timeout; forcing termination.");
			m_pServerThread->terminate();
			m_pServerThread->wait(1000);
		}
		delete m_pServerThread;
		m_pServerThread = nullptr;
	}

	// 4. Now safe to delete brokers — all resource releasers have run.
	if (m_pRenderProgress) {
		delete m_pRenderProgress;
		m_pRenderProgress = nullptr;
	}
	if (m_pEventBroker) {
		delete m_pEventBroker;
		m_pEventBroker = nullptr;
	}

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

void DzScriptServerPane::updateUI()
{
	if (m_bRunning) {
		QString authStatus = m_auth.isEnabled() ? tr("Protected") : tr("⚠ Unprotected");
		m_pStatusLabel->setText(tr("Running on %1:%2 (%3)")
			.arg(m_sHost).arg(m_nPort).arg(authStatus));
		m_pStartBtn->setEnabled(false);
		m_pStopBtn->setEnabled(true);
		m_pHostEdit->setEnabled(false);
		m_pPortSpin->setEnabled(false);
		m_pTimeoutSpin->setEnabled(false);
		m_pAuthEnabledCheck->setEnabled(false);
		m_pRegenTokenBtn->setEnabled(false);
		m_pIpWhitelistCheck->setEnabled(false);
		m_pIpWhitelistEdit->setEnabled(false);
		m_pRateLimitCheck->setEnabled(false);
		m_pRateLimitMaxSpin->setEnabled(false);
		m_pRateLimitWindowSpin->setEnabled(false);
		m_pMaxConcurrentSpin->setEnabled(false);
		m_pMaxBodySizeSpin->setEnabled(false);
		m_pMaxScriptLengthSpin->setEnabled(false);
	} else {
		m_pStatusLabel->setText(tr("Stopped"));
		m_pStartBtn->setEnabled(true);
		m_pStopBtn->setEnabled(false);
		m_pHostEdit->setEnabled(true);
		m_pPortSpin->setEnabled(true);
		m_pTimeoutSpin->setEnabled(true);
		m_pAuthEnabledCheck->setEnabled(true);
		m_pRegenTokenBtn->setEnabled(true);
		m_pIpWhitelistCheck->setEnabled(true);
		m_pIpWhitelistEdit->setEnabled(true);
		m_pRateLimitCheck->setEnabled(true);
		m_pRateLimitMaxSpin->setEnabled(true);
		m_pRateLimitWindowSpin->setEnabled(true);
		m_pMaxConcurrentSpin->setEnabled(true);
		m_pMaxBodySizeSpin->setEnabled(true);
		m_pMaxScriptLengthSpin->setEnabled(true);
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

void DzScriptServerPane::appendLogBytes(const QByteArray& data)
{
    appendLog(QString::fromUtf8(data.constData(), data.size()));
}

// ─── Route setup helpers ─────────────────────────────────────────────────────

static inline QByteArray stdToQBA(const std::string& s)
{
    return QByteArray(s.c_str(), static_cast<int>(s.size()));
}

// RAII guard for the concurrent-request counter.
// Increments on construction; decrements automatically on destruction.
// operator bool() returns false if the limit was already reached (counter not held).
struct ActiveRequestSlot {
	QAtomicInt& counter;
	bool        held;

	ActiveRequestSlot(QAtomicInt& c, int limit) : counter(c), held(false) {
		held = (c.fetchAndAddOrdered(1) < limit);
		if (!held) c.deref();
	}
	~ActiveRequestSlot() { if (held) counter.deref(); }
	operator bool() const { return held; }

private:
	ActiveRequestSlot(const ActiveRequestSlot&);
	ActiveRequestSlot& operator=(const ActiveRequestSlot&);
};

static HttpContext toContext(const httplib::Request& req)
{
	HttpContext ctx;
	ctx.body       = req.body;
	ctx.remoteAddr = req.remote_addr.empty() ? "unknown" : req.remote_addr;
	if (req.matches.size() > 1)
		ctx.urlMatch = req.matches[1].str();
	ctx.headers["x-api-token"]  = req.get_header_value("X-API-Token");
	ctx.headers["authorization"] = req.get_header_value("Authorization");
	for (httplib::Params::const_iterator it = req.params.begin();
	     it != req.params.end(); ++it)
		ctx.queryParams[it->first] = it->second;
	return ctx;
}

static void applyContext(const HttpContext& ctx, httplib::Response& res)
{
	res.status = ctx.responseStatus;
	if (!ctx.responseBody.empty())
		res.set_content(ctx.responseBody, "application/json");
}

// ─── Route setup ──────────────────────────────────────────────────────────────
//
// THREADING RULE: httplib invokes these handlers on raw std::threads (not QThreads).
// Handlers must do NO Qt work beyond calling handler/middleware methods that are
// themselves designed for HTTP-thread use (mutex-protected data, QueuedConnection logs).
// All DzScript execution happens on the main thread via Qt::BlockingQueuedConnection.

void DzScriptServerPane::setupRoutes()
{
	// ── Middleware chains ─────────────────────────────────────────────────────
	m_pAuthChain.reset(new MiddlewareChain());
	m_pAuthChain->add(new AuthMiddleware(m_auth, m_metrics, this));

	m_pExecuteSyncChain.reset(new MiddlewareChain());
	m_pExecuteSyncChain->add(new IPWhitelistMiddleware(m_ipWhitelist, this));
	m_pExecuteSyncChain->add(new RateLimitMiddleware(m_rateLimiter, this));
	m_pExecuteSyncChain->add(new BodySizeMiddleware(m_nMaxBodySizeMB));
	m_pExecuteSyncChain->add(new AuthMiddleware(m_auth, m_metrics, this));

	m_pBaseExecuteChain.reset(new MiddlewareChain());
	m_pBaseExecuteChain->add(new IPWhitelistMiddleware(m_ipWhitelist, this));
	m_pBaseExecuteChain->add(new RateLimitMiddleware(m_rateLimiter, this));
	m_pBaseExecuteChain->add(new AuthMiddleware(m_auth, m_metrics, this));

	// ── Request handlers ──────────────────────────────────────────────────────
	m_pStatusHandler.reset(new StatusHandler(DZSRV_VERSION_STR));
	m_pHealthHandler.reset(new HealthHandler(this));
	m_pMetricsHandler.reset(new MetricsHandler(this));
	m_pExecuteHandler.reset(new ExecuteScriptHandler(this));
	m_pRegisterHandler.reset(new ScriptRegisterHandler(this));
	m_pScriptListHandler.reset(new ScriptListHandler(this));
	m_pScriptDeleteHandler.reset(new ScriptDeleteHandler(this));
	m_pScriptExecHandler.reset(new ScriptExecuteHandler(this));
	m_pAsyncExecHandler.reset(new AsyncExecuteHandler(this));
	m_pAsyncScriptHandler.reset(new AsyncScriptHandler(this));
	m_pAsyncStatusHandler.reset(new AsyncStatusHandler(this));
	m_pAsyncResultHandler.reset(new AsyncResultHandler(this));
	m_pAsyncCancelHandler.reset(new AsyncCancelHandler(this));
	m_pAsyncListHandler.reset(new AsyncListHandler(this));
	m_pRenderHandler.reset(new RenderHandler(this));

	// ── Routes ───────────────────────────────────────────────────────────────

	m_pServer->Get("/status", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		m_pStatusHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/health", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		m_pHealthHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/metrics", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		m_pMetricsHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Post("/execute", [this](const httplib::Request& req, httplib::Response& res) {
		ActiveRequestSlot slot(m_nActiveRequests, m_nMaxConcurrentRequests);
		if (!slot) {
			res.status = 429;
			res.set_content(ErrorResponse::build(ErrorCode::CONCURRENT_LIMIT_EXCEEDED), "application/json");
			return;
		}
		QMetaObject::invokeMethod(this, "updateActiveRequestsLabel", Qt::QueuedConnection);

		auto ctx = toContext(req);
		if (m_pExecuteSyncChain->run(ctx)) m_pExecuteHandler->handle(ctx);
		applyContext(ctx, res);
		QMetaObject::invokeMethod(this, "updateActiveRequestsLabel", Qt::QueuedConnection);
	});

	m_pServer->Post("/scripts/register", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pAuthChain->run(ctx)) m_pRegisterHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/scripts", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pAuthChain->run(ctx)) m_pScriptListHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Delete("/scripts/([^/]+)", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pAuthChain->run(ctx)) m_pScriptDeleteHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Post("/scripts/([^/]+)/execute", [this](const httplib::Request& req, httplib::Response& res) {
		ActiveRequestSlot slot(m_nActiveRequests, m_nMaxConcurrentRequests);
		if (!slot) {
			res.status = 429;
			res.set_content(ErrorResponse::build(ErrorCode::CONCURRENT_LIMIT_EXCEEDED), "application/json");
			return;
		}
		QMetaObject::invokeMethod(this, "updateActiveRequestsLabel", Qt::QueuedConnection);
		auto ctx = toContext(req);
		if (m_pBaseExecuteChain->run(ctx)) m_pScriptExecHandler->handle(ctx);
		applyContext(ctx, res);
		QMetaObject::invokeMethod(this, "updateActiveRequestsLabel", Qt::QueuedConnection);
	});

	// ── Async endpoints ──────────────────────────────────────────────────────

	m_pServer->Post("/execute/async", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pBaseExecuteChain->run(ctx)) m_pAsyncExecHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Post("/scripts/([^/]+)/async", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pBaseExecuteChain->run(ctx)) m_pAsyncScriptHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/requests/([^/]+)/status", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pAuthChain->run(ctx)) m_pAsyncStatusHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/requests/([^/]+)/result", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pAuthChain->run(ctx)) m_pAsyncResultHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Delete("/requests/([^/]+)", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pAuthChain->run(ctx)) m_pAsyncCancelHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/requests", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pAuthChain->run(ctx)) m_pAsyncListHandler->handle(ctx);
		applyContext(ctx, res);
	});

	// ── Render endpoint ───────────────────────────────────────────────────────

	m_pServer->Post("/render", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pBaseExecuteChain->run(ctx)) m_pRenderHandler->handle(ctx);
		applyContext(ctx, res);
	});

	// ── Scene event stream (SSE) ──────────────────────────────────────────────
	//
	// GET /scene/events[?filter=node,selection,scene,time,render,light,camera,skeleton]
	//
	// Streams DAZ scene-change notifications as Server-Sent Events.  The
	// connection is kept open indefinitely; a ":keepalive" comment is sent
	// every 15 seconds so clients can detect disconnects.
	//
	// Each event frame:   data: {"type":"...","ts":<ms>,"data":{...}}\n\n
	// Keepalive frame:    :keepalive\n\n

	m_pServer->Get("/scene/events", [this](const httplib::Request& req, httplib::Response& res) {
		// Auth check — run the chain synchronously before entering streaming mode.
		// We cannot call applyContext() here (it would finalize the response body),
		// so on failure we set status/content directly.
		{
			auto ctx = toContext(req);
			if (!m_pAuthChain->run(ctx)) {
				res.status = ctx.responseStatus;
				res.set_content(ctx.responseBody, "application/json");
				return;
			}
		}

		// Parse ?filter= into a bitmask.  Absent or empty → all categories.
		int filterMask = SceneEventFilter::All;
		if (req.has_param("filter") && !req.get_param_value("filter").empty()) {
			filterMask = SceneEventFilter::None;
			std::string filterStr = req.get_param_value("filter");
			// Split on commas and map each token to its bitmask.
			std::string token;
			filterStr += ','; // sentinel
			for (size_t i = 0; i < filterStr.size(); ++i) {
				char c = filterStr[i];
				if (c == ',') {
					if      (token == "node")      filterMask |= SceneEventFilter::Node;
					else if (token == "skeleton")  filterMask |= SceneEventFilter::Skeleton;
					else if (token == "light")     filterMask |= SceneEventFilter::Light;
					else if (token == "camera")    filterMask |= SceneEventFilter::Camera;
					else if (token == "selection") filterMask |= SceneEventFilter::Selection;
					else if (token == "scene")     filterMask |= SceneEventFilter::Scene;
					else if (token == "time")      filterMask |= SceneEventFilter::Time;
					else if (token == "render")    filterMask |= SceneEventFilter::Render;
					token.clear();
				} else {
					token += c;
				}
			}
			if (filterMask == SceneEventFilter::None)
				filterMask = SceneEventFilter::All; // unknown tokens → default to all
		}

		res.set_header("Cache-Control", "no-cache");
		res.set_header("Connection",    "keep-alive");
		res.set_header("X-Accel-Buffering", "no"); // disable nginx proxy buffering

		SubscriberQueue* queue = new SubscriberQueue(filterMask);
		m_pEventBroker->registerSubscriber(queue);
		QMetaObject::invokeMethod(this, "updateEventClientsLabel", Qt::QueuedConnection);

		// The chunked content provider is called repeatedly by httplib on the
		// HTTP handler thread until it returns false or the client disconnects.
		// Pop timeout (3 s) is kept well under the server's default 5 s write
		// timeout so that each iteration writes a keepalive before the loop's
		// wait_writable() check can time out.
		res.set_chunked_content_provider("text/event-stream",
			[queue](size_t /*offset*/, httplib::DataSink& sink) -> bool {
				QString event = queue->pop(3000 /*ms*/);

				if (event.isEmpty()) {
					// Timeout or closed queue — send keepalive to prove the
					// connection is live.  A closed queue returns "" every call,
					// so on server shutdown this unblocks quickly and the next
					// is_shutting_down() check ends the loop.
					static const char ka[] = ":keepalive\n\n";
					return sink.write(ka, sizeof(ka) - 1);
				}

				QByteArray payload = ("data: " + event + "\n\n").toUtf8();
				return sink.write(payload.constData(), static_cast<size_t>(payload.size()));
			},
			[this, queue](bool /*success*/) {
				// Resource releaser — called exactly once when the stream closes.
				// stopServer() guarantees the broker outlives all releasers by
				// deleting it only after m_pServerThread->wait() returns (which
				// joins all request-handler threads via ThreadPool::shutdown()).
				m_pEventBroker->unregisterSubscriber(queue);
				delete queue;
				QMetaObject::invokeMethod(this, "updateEventClientsLabel", Qt::QueuedConnection);
			}
		);
	});

	// GET /render/:id/progress
	//
	// SSE stream: emits a single "progress" event (percent:0) when the render
	// starts executing, then a terminal "complete" or "error" event when done.
	// DAZ SDK exposes no per-frame progress signal, so no intermediate percent
	// updates are possible. Clients connecting after completion receive the
	// stored terminal event immediately.
	m_pServer->Get("/render/([^/]+)/progress", [this](const httplib::Request& req, httplib::Response& res) {
		{
			auto ctx = toContext(req);
			if (!m_pAuthChain->run(ctx)) {
				res.status = ctx.responseStatus;
				res.set_content(ctx.responseBody, "application/json");
				return;
			}
		}

		QString requestId = QString::fromStdString(req.matches[1].str());
		if (!requestId.startsWith("rnd-")) {
			res.status = 404;
			res.set_content("{\"error\":\"Not a render request\"}", "application/json");
			return;
		}

		auto statusPair = m_pAsyncMgr->getStatusJson(requestId.toStdString());
		if (statusPair.first == 404) {
			res.status = 404;
			res.set_content("{\"error\":\"Render request not found\"}", "application/json");
			return;
		}

		SubscriberQueue* queue = new SubscriberQueue();
		if (!m_pRenderProgress->watchRequest(requestId, queue)) {
			delete queue;
			res.status = 404;
			res.set_content("{\"error\":\"Render request not found\"}", "application/json");
			return;
		}

		res.set_header("Cache-Control",    "no-cache");
		res.set_header("Connection",       "keep-alive");
		res.set_header("X-Accel-Buffering","no");
		QMetaObject::invokeMethod(this, "updateEventClientsLabel", Qt::QueuedConnection);

		RenderProgressBroker* broker = m_pRenderProgress;
		res.set_chunked_content_provider("text/event-stream",
			[queue](size_t, httplib::DataSink& sink) -> bool {
				QString event = queue->pop(3000);
				if (event.isEmpty()) {
					if (queue->isClosed()) return false;
					static const char ka[] = ":keepalive\n\n";
					return sink.write(ka, sizeof(ka) - 1);
				}
				QByteArray payload = event.toUtf8();
				bool ok = sink.write(payload.constData(), payload.size());
				return ok && !queue->isClosed();
			},
			[this, broker, requestId, queue](bool) {
				broker->unwatchRequest(requestId, queue);
				delete queue;
				QMetaObject::invokeMethod(this, "updateEventClientsLabel", Qt::QueuedConnection);
			}
		);
	});

	applyPluginRoutes();
}

// ─── Plugin Route Registration ────────────────────────────────────────────────

bool DzScriptServerPane::registerPluginRoute(const QString& method, const QString& path,
                                              QObject* receiver, const QString& slotName)
{
	if (!receiver || path.isEmpty() || slotName.isEmpty())
		return false;

	const QString m = method.toUpper();
	if (m != "GET" && m != "POST" && m != "PUT" && m != "DELETE" && m != "PATCH")
		return false;

	PluginRoute r;
	r.method    = m;
	r.path      = path;
	r.receiver  = receiver;
	r.slotName  = slotName;

	QMutexLocker lock(&m_pluginRoutesMutex);
	for (int i = 0; i < m_pluginRoutes.size(); ++i) {
		if (m_pluginRoutes[i].method == m && m_pluginRoutes[i].path == path) {
			m_pluginRoutes[i] = r;
			return true;
		}
	}
	m_pluginRoutes.append(r);
	return true;
}

void DzScriptServerPane::unregisterPluginRoute(const QString& method, const QString& path)
{
	const QString m = method.toUpper();
	QMutexLocker lock(&m_pluginRoutesMutex);
	for (int i = 0; i < m_pluginRoutes.size(); ++i) {
		if (m_pluginRoutes[i].method == m && m_pluginRoutes[i].path == path) {
			m_pluginRoutes.removeAt(i);
			return;
		}
	}
}

void DzScriptServerPane::applyPluginRoutes()
{
	QMutexLocker lock(&m_pluginRoutesMutex);
	for (int i = 0; i < m_pluginRoutes.size(); ++i) {
		const PluginRoute& r = m_pluginRoutes[i];
		QPointer<QObject> receiver = r.receiver;
		QByteArray slotBytes       = r.slotName.toLatin1();

		auto handler = [receiver, slotBytes](const httplib::Request& req, httplib::Response& res) {
			if (!receiver) {
				res.status = 503;
				res.set_content("{\"error\":\"plugin handler unloaded\"}", "application/json");
				return;
			}
			QByteArray body(req.body.c_str(), (int)req.body.size());
			QByteArray ip(req.remote_addr.c_str(), (int)req.remote_addr.size());
			HttpResult result;
			QMetaObject::invokeMethod(receiver.data(), slotBytes.constData(),
			                          Qt::BlockingQueuedConnection,
			                          Q_RETURN_ARG(HttpResult, result),
			                          Q_ARG(QByteArray, body),
			                          Q_ARG(QByteArray, ip));
			res.status = result.first;
			if (!result.second.isEmpty())
				res.set_content(result.second.constData(), "application/json");
		};

		std::string path = r.path.toStdString();
		if      (r.method == "GET")    m_pServer->Get(path, handler);
		else if (r.method == "POST")   m_pServer->Post(path, handler);
		else if (r.method == "PUT")    m_pServer->Put(path, handler);
		else if (r.method == "DELETE") m_pServer->Delete(path, handler);
		else if (r.method == "PATCH")  m_pServer->Patch(path, handler);
	}
}

// ─── Script Registry public API (called from HTTP threads) ───────────────────

std::string DzScriptServerPane::listScriptsJson() const
{
	struct Entry { std::string id, description; long long registeredAtMs; };
	std::vector<Entry> entries;
	{
		QMutexLocker lock(&m_scriptRegistry.mutex);
		entries.reserve(m_scriptRegistry.scripts.size());
		for (QMap<QByteArray, RegisteredScript>::const_iterator it = m_scriptRegistry.scripts.begin();
		     it != m_scriptRegistry.scripts.end(); ++it) {
			entries.push_back({
			    std::string(it.key().constData(), it.key().size()),
			    JsonStd::qstrToStd(it.value().description),
			    (long long)it.value().registeredAt.toMSecsSinceEpoch()
			});
		}
	}

	std::string items;
	for (size_t i = 0; i < entries.size(); ++i) {
		if (i > 0) items += ",";
		items += "{\"name\":\"" + JsonStd::escape(entries[i].id) + "\"";
		items += ",\"description\":\"" + JsonStd::escape(entries[i].description) + "\"";
		items += ",\"registered_at\":\"" + JsonStd::msecToIso(entries[i].registeredAtMs) + "\"}";
	}
	std::string s = "{\"scripts\":[" + items + "]";
	s += ",\"count\":" + std::to_string(entries.size()) + "}";
	return s;
}

std::pair<int, std::string> DzScriptServerPane::deleteRegistryScriptJson(
    const std::string& id, const std::string& clientIP)
{
	bool removed = false;
	{
		QByteArray key(id.c_str(), (int)id.size());
		QMutexLocker lock(&m_scriptRegistry.mutex);
		removed = m_scriptRegistry.scripts.remove(key) > 0;
	}

	if (!removed) {
		std::string body = "{\"success\":false,\"error\":\"Script not found: '";
		body += JsonStd::escape(id) + "'\"}";
		return {404, body};
	}

	std::string logLine = "[" + JsonStd::currentTime() + "] [" + clientIP + "] [REGISTRY] Deleted script: " + id;
	QMetaObject::invokeMethod(this, "appendLogBytes", Qt::QueuedConnection,
	    Q_ARG(QByteArray, QByteArray(logLine.c_str(), (int)logLine.size())));

	std::string body = "{\"success\":true,\"id\":\"" + JsonStd::escape(id) + "\"}";
	return {200, body};
}

bool DzScriptServerPane::lookupRegistryScript(const std::string& id, std::string& outScript) const
{
	QByteArray key(id.c_str(), (int)id.size());
	QMutexLocker lock(&m_scriptRegistry.mutex);
	if (!m_scriptRegistry.scripts.contains(key))
		return false;
	outScript = JsonStd::qstrToStd(m_scriptRegistry.scripts.value(key).script);
	return true;
}

// ─── Async Request public API (called from HTTP threads) ──────────────────────

QString DzScriptServerPane::enqueueAsyncRequest(const QString& scriptText,
                                                const QVariantMap& args,
                                                const QString& idPrefix,
                                                qint64& outSubmittedAt,
                                                QString& outError)
{
	AsyncRequestManager::SubmitResult r = m_pAsyncMgr->submit(scriptText, args, idPrefix);
	outSubmittedAt = r.submittedAt;
	outError       = r.error;
	if (!r.accepted) {
		std::string msg = "[WARN] Async queue rejected: " + JsonStd::qstrToStd(r.error);
		QMetaObject::invokeMethod(this, "appendLogBytes", Qt::QueuedConnection,
		    Q_ARG(QByteArray, QByteArray(msg.c_str(), (int)msg.size())));
	}
	return r.id;
}

std::pair<int, std::string> DzScriptServerPane::getAsyncStatusJson(const std::string& requestId) const
{
	return m_pAsyncMgr->getStatusJson(requestId);
}

std::pair<int, std::string> DzScriptServerPane::getAsyncResultJson(const std::string& requestId,
                                                                   bool doWait, int timeoutSec)
{
	return m_pAsyncMgr->getResultJson(requestId, doWait, timeoutSec);
}

std::pair<int, std::string> DzScriptServerPane::cancelAsyncRequestJson(const std::string& requestId,
                                                                       const std::string& clientIP)
{
	std::pair<int, std::string> result = m_pAsyncMgr->cancelJson(requestId, clientIP);
	if (result.first == 200) {
		std::string logLine = "[" + JsonStd::currentTime() + "] [ASYNC CANCEL] " + requestId;
		QMetaObject::invokeMethod(this, "appendLogBytes", Qt::QueuedConnection,
		    Q_ARG(QByteArray, QByteArray(logLine.c_str(), (int)logLine.size())));
	}
	return result;
}

std::string DzScriptServerPane::listAsyncRequestsJson(const std::string& statusFilter) const
{
	return m_pAsyncMgr->listJson(statusFilter);
}

// ─── Main-thread request handler ──────────────────────────────────────────────

HttpResult DzScriptServerPane::handleExecuteRequest(const QByteArray& jsonBody, const QByteArray& clientIP)
{
	QTime startTime = QTime::currentTime();
	QString clientIPStr = QString::fromUtf8(clientIP.constData(), clientIP.size());
	QString requestId = MetricsCollector::generateRequestId();

	// Parse JSON body (QScriptEngine is a QObject — only safe on a Qt-managed thread)
	QString bodyStr = QString::fromUtf8(jsonBody.constData(), jsonBody.size());

	QScriptEngine parseEngine;
	QScriptValue parsed = parseEngine.evaluate("(" + bodyStr + ")");
	if (parseEngine.hasUncaughtException()) {
		QString detail = QString("line %1: %2")
			.arg(parseEngine.uncaughtExceptionLineNumber())
			.arg(parseEngine.uncaughtException().toString());
		appendLog(QString("[%1] [%2] [ERR] [0ms] [%3] JSON parse error")
			.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
			.arg(clientIPStr).arg(requestId));
		m_metrics.recordRequest(false);
		return HttpResult(400,
			stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON, JsonStd::qstrToStd(detail))));
	}

	QVariantMap bodyMap  = parsed.toVariant().toMap();
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

	// Capture dzApp debug output (print() in DazScript)
	m_aCapturedLogLines.clear();
	m_bCapturingLog = true;
	connect(dzApp, SIGNAL(debugMsg(const QString&)),
	        this,  SLOT(onMessagePosted(const QString&)),
	        Qt::DirectConnection);

	QScopedPointer<DzScript> script(new DzScript());

	if (!scriptFile.isEmpty()) {
		// loadFromFile sets the filename so getScriptFileName() and relative
		// include() calls work correctly inside the script.
		if (!script->loadFromFile(scriptFile)) {
			disconnect(dzApp, SIGNAL(debugMsg(const QString&)),
			           this,  SLOT(onMessagePosted(const QString&)));
			m_bCapturingLog = false;
			m_metrics.recordRequest(false);
			return HttpResult(400,
				stdToQBA(ErrorResponse::build(
					ErrorCode::SCRIPT_FILE_LOAD_FAILED, JsonStd::qstrToStd(scriptFile))));
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

	script.reset();  // Destroy script before disconnecting the signal

	disconnect(dzApp, SIGNAL(debugMsg(const QString&)),
	           this,  SLOT(onMessagePosted(const QString&)));
	m_bCapturingLog = false;

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
	                                 success ? scriptResult : QVariant(),
	                                 m_aCapturedLogLines,
	                                 errorVar,
	                                 requestId);
	return HttpResult(200, body.toUtf8());
}

// ─── Script Registry handlers (main thread) ───────────────────────────────────

HttpResult DzScriptServerPane::handleRegisterScript(const QByteArray& jsonBody, const QByteArray& clientIP)
{
	QString clientIPStr = QString::fromUtf8(clientIP.constData(), clientIP.size());

	QScriptEngine parseEngine;
	QScriptValue  parsed = parseEngine.evaluate(
		"(" + QString::fromUtf8(jsonBody.constData(), jsonBody.size()) + ")");
	if (parseEngine.hasUncaughtException()) {
		return HttpResult(400,
			stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));
	}

	QVariantMap body    = parsed.toVariant().toMap();
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

	RegisteredScript entry;
	entry.description  = description;
	entry.script       = script;
	entry.registeredAt = QDateTime::currentDateTime();

	bool isUpdate;
	{
		QByteArray key = name.toUtf8();
		QMutexLocker lock(&m_scriptRegistry.mutex);
		isUpdate = m_scriptRegistry.scripts.contains(key);
		m_scriptRegistry.scripts.insert(key, entry);
	}

	appendLog(QString("[%1] [%2] [REGISTRY] %3 script: %4")
		.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
		.arg(clientIPStr)
		.arg(isUpdate ? "Updated" : "Registered")
		.arg(name));

	JsonBuilder json;
	json.startObject();
	json.addMember("success",       true);
	json.addMember("id",            name);
	json.addMember("registered_at", entry.registeredAt.toString(Qt::ISODate));
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
		QScriptEngine parseEngine;
		QScriptValue  parsed = parseEngine.evaluate(
			"(" + QString::fromUtf8(requestBody.constData(), requestBody.size()) + ")");
		if (!parseEngine.hasUncaughtException())
			argsMap = parsed.toVariant().toMap().value("args").toMap();
	}

	// Execute
	m_aCapturedLogLines.clear();
	m_bCapturingLog = true;
	connect(dzApp, SIGNAL(debugMsg(const QString&)),
	        this,  SLOT(onMessagePosted(const QString&)),
	        Qt::DirectConnection);

	QScopedPointer<DzScript> script(new DzScript());
	script->setCode(QString::fromUtf8(scriptText.constData(), scriptText.size()));

	QVariantList execArgs;
	execArgs << QVariant(argsMap);

	QVariant scriptResult;
	QVariant errorVar;
	bool     success  = true;
	bool     executed = script->execute(execArgs);
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

	script.reset();  // Destroy script before disconnecting the signal
	disconnect(dzApp, SIGNAL(debugMsg(const QString&)),
	           this,  SLOT(onMessagePosted(const QString&)));
	m_bCapturingLog = false;

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
		                  success ? scriptResult : QVariant(),
		                  m_aCapturedLogLines,
		                  errorVar,
		                  requestId).toUtf8());
}

static HttpResult buildQueuedResponse(const QString& requestId, qint64 submittedAt)
{
	std::string resp = "{\"request_id\":\"";
	resp += JsonStd::escape(JsonStd::qstrToStd(requestId));
	resp += "\",\"status\":\"queued\",\"submitted_at\":\"";
	resp += JsonStd::msecToIso((long long)submittedAt);
	resp += "\"}";
	return HttpResult(200, QByteArray(resp.c_str(), (int)resp.size()));
}

HttpResult DzScriptServerPane::handleAsyncExecuteEnqueue(const QByteArray& jsonBody)
{
	QScriptEngine parseEngine;
	QScriptValue  parsed = parseEngine.evaluate(
		"(" + QString::fromUtf8(jsonBody.constData(), jsonBody.size()) + ")");
	if (parseEngine.hasUncaughtException()) {
		return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));
	}

	QVariantMap body       = parsed.toVariant().toMap();
	QString     scriptText = body.value("script").toString();

	ValidationResult vr = RequestValidator::validateRequiredField(scriptText, "script");
	if (!vr.valid)
		return HttpResult(vr.httpStatus(), stdToQBA(vr.toErrorJson()));

	qint64  submittedAt  = 0;
	QString enqueueError;
	QString requestId = enqueueAsyncRequest(
		scriptText, body.value("args").toMap(), "execute", submittedAt, enqueueError);

	if (requestId.isEmpty())
		return HttpResult(503, stdToQBA(ErrorResponse::build(
			ErrorCode::SERVER_UNAVAILABLE, JsonStd::qstrToStd(enqueueError))));

	return buildQueuedResponse(requestId, submittedAt);
}

HttpResult DzScriptServerPane::handleAsyncScriptEnqueue(
	const QByteArray& scriptBytes,
	const QByteArray& scriptIdBytes,
	const QByteArray& bodyBytes)
{
	QString scriptText = QString::fromUtf8(scriptBytes.constData(), scriptBytes.size());
	QString scriptId   = QString::fromUtf8(scriptIdBytes.constData(), scriptIdBytes.size());

	QVariantMap argsMap;
	if (!bodyBytes.isEmpty()) {
		QScriptEngine parseEngine;
		QScriptValue  parsed = parseEngine.evaluate(
			"(" + QString::fromUtf8(bodyBytes.constData(), bodyBytes.size()) + ")");
		if (!parseEngine.hasUncaughtException())
			argsMap = parsed.toVariant().toMap().value("args").toMap();
	}

	qint64  submittedAt  = 0;
	QString enqueueError;
	QString requestId = enqueueAsyncRequest(
		scriptText, argsMap, "script", submittedAt, enqueueError);

	if (requestId.isEmpty())
		return HttpResult(503, stdToQBA(ErrorResponse::build(
			ErrorCode::SERVER_UNAVAILABLE, JsonStd::qstrToStd(enqueueError))));

	appendLog(QString("[%1] [ASYNC QUEUED] script:%2 -> %3")
		.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
		.arg(scriptId).arg(requestId));

	return buildQueuedResponse(requestId, submittedAt);
}

// ─── Render script generation ─────────────────────────────────────────────────

namespace {

struct FigureSpec {
    QString     name;
    QVariantMap morphs;
};

// Builds the DazScript that applies morphs and triggers the render.
// The script runs on the main thread via processNextAsyncRequest().
//
// Structure:
//   1. Re-validate figure refs (belt-and-suspenders; scene may have changed since enqueue).
//   2. Optionally reset all float properties on each figure to default (reset_morphs).
//   3. Apply morphs dict via findPropertyByLabel(); unknown keys are silently skipped.
//   4. Configure render options and call App.getRenderMgr().render(opts).
//   5. Return {success:true, output_path:"..."} as a JS object.
//
// NOTE: DAZ DazScript render options method names (setImageFile, setAspectWidth,
// setAspectHeight, setActiveCamera) need to be verified against a running DAZ Studio
// instance. The names used here are based on the DAZ SDK docs and existing examples.
static QString buildRenderScript(
    const QString& outputPath,
    int width, int height,
    const QString& camera,
    const QString& engine,
    int iraySamples,
    bool resetMorphs,
    const QList<FigureSpec>& figures)
{
    // Embed figure specs as a JSON array literal — valid JS object literal syntax.
    QString figureJson = "[";
    for (int i = 0; i < figures.size(); ++i) {
        if (i > 0) figureJson += ",";
        figureJson += "{\"name\":\"";
        figureJson += QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(figures[i].name)));
        figureJson += "\",\"morphs\":";
        figureJson += QString::fromStdString(JsonStd::variantToJson(QVariant(figures[i].morphs)));
        figureJson += "}";
    }
    figureJson += "]";

    QString outputPathEsc = QString::fromStdString(
        JsonStd::escape(JsonStd::qstrToStd(outputPath)));
    QString cameraEsc = camera.isEmpty() ? QString("null")
        : "\"" + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(camera))) + "\"";
    QString engineEsc = engine.isEmpty() ? QString("null")
        : "\"" + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(engine))) + "\"";

    QString script;
    script += "(function() {\n";

    // ── Figure specs ──────────────────────────────────────────────────────
    script += "  var figures = " + figureJson + ";\n";
    script += "  var outputPath = \"" + outputPathEsc + "\";\n";
    script += "  var cameraName = " + cameraEsc + ";\n";
    script += "  var engineName = " + engineEsc + ";\n";
    script += "  var width = " + QString::number(width) + ";\n";
    script += "  var height = " + QString::number(height) + ";\n";
    script += "  var iraySamples = " + QString::number(iraySamples) + ";\n";
    script += "  var resetMorphs = " + QString(resetMorphs ? "true" : "false") + ";\n\n";

    // ── Pre-flight: validate all figure references ────────────────────────
    script +=
        "  for (var i = 0; i < figures.length; i++) {\n"
        "    if (!Scene.findNodeByLabel(figures[i].name))\n"
        "      return {success: false, error: 'Figure not found: ' + figures[i].name};\n"
        "  }\n\n";

    // ── Reset morphs ──────────────────────────────────────────────────────
    // Resets all DzFloatProperty values to their defaults on each figure.
    // This gives a clean morph baseline before applying the variant's morph dict.
    script +=
        "  if (resetMorphs) {\n"
        "    for (var i = 0; i < figures.length; i++) {\n"
        "      var node = Scene.findNodeByLabel(figures[i].name);\n"
        "      var props = node.getPropertyList();\n"
        "      for (var j = 0; j < props.length; j++) {\n"
        "        if (props[j].inherits('DzFloatProperty'))\n"
        "          props[j].setValue(props[j].getDefaultValue());\n"
        "      }\n"
        "    }\n"
        "  }\n\n";

    // ── Apply morphs ──────────────────────────────────────────────────────
    // Unknown morph names are silently skipped (non-fatal per design decision).
    script +=
        "  for (var i = 0; i < figures.length; i++) {\n"
        "    var node = Scene.findNodeByLabel(figures[i].name);\n"
        "    var morphDict = figures[i].morphs;\n"
        "    for (var k in morphDict) {\n"
        "      if (morphDict.hasOwnProperty(k)) {\n"
        "        var prop = node.findPropertyByLabel(k);\n"
        "        if (prop) prop.setValue(morphDict[k]);\n"
        "      }\n"
        "    }\n"
        "  }\n\n";

    // ── Configure render options ──────────────────────────────────────────
    // SDK-verified method names (dzrenderoptions.h / dzrendermgr.h / dzscene.h):
    //   renderImgFilename   Q_PROPERTY WRITE setRenderImgFilename
    //   renderImgToId       Q_PROPERTY WRITE setRenderImgToId  (2 = DirectToFile)
    //   imageSize           Q_PROPERTY WRITE setImageSize (QSize)
    //   Scene.findCameraByLabel()  confirmed in dzscene.h
    //   App.getViewportMgr().setActiveCamera()  confirmed in dzviewportmgr.h
    //   renderMgr.doRender(opts)  confirmed in dzrendermgr.h
    //   Engine switching: renderMgr.setActiveRenderer(DzRenderer*) — requires
    //     renderer lookup by class name; names are runtime-registered so not in
    //     the SDK headers. Left as a TODO until tested against a live instance.
    //   iray_samples: not a DzRenderOptions property — it lives in iray's own
    //     render settings, accessible via the iray renderer object. TODO.
    script +=
        "  var renderMgr = App.getRenderMgr();\n"
        "  var opts = renderMgr.getRenderOptions();\n"
        "  opts.renderImgFilename = outputPath;\n"
        "  opts.renderImgToId = 2;\n";  // DirectToFile

    // QSize constructor confirmed in DAZ DazScript: new QSize(w, h)
    // Qt.size() is NOT available — Qt global is undefined in this engine.
    script +=
        "  if (width > 0) opts.imageSize = new QSize(width, height);\n";

    script +=
        "  if (cameraName) {\n"
        "    var cam = Scene.findCameraByLabel(cameraName);\n"
        "    if (cam) App.getViewportMgr().setActiveCamera(cam);\n"
        "  }\n";

    // Engine class name map — confirmed: iray="DzIrayRenderer".
    // 3Delight and Filament class names follow the same Dz*Renderer pattern but
    // need verification on a system with those plugins installed.
    script +=
        "  if (engineName) {\n"
        "    var engineMap = {\"iray\": \"DzIrayRenderer\", \"3delight\": \"Dz3DelightRenderer\", \"filament\": \"DzFilamentRenderer\"};\n"
        "    var engineClass = engineMap[engineName.toLowerCase()];\n"
        "    if (engineClass) {\n"
        "      var renderer = renderMgr.findRenderer(engineClass);\n"
        "      if (renderer) renderMgr.setActiveRenderer(renderer);\n"
        "    }\n"
        "  }\n";

    // iray_samples: not exposed on DzRenderOptions or the DzIrayRenderer object
    // in DazScript. DAZ stores iray-specific settings outside the standard render
    // options API; the access path is not yet determined. Field is accepted but
    // silently ignored until resolved.
    script += "\n";

    // ── Render ────────────────────────────────────────────────────────────
    script +=
        "  renderMgr.doRender(opts);\n"
        "  return {success: true, output_path: outputPath};\n"
        "})();\n";

    return script;
}

} // namespace

// ─────────────────────────────────────────────────────────────────────────────

HttpResult DzScriptServerPane::handleAsyncRenderEnqueue(const QByteArray& jsonBody)
{
    // ── Parse body ────────────────────────────────────────────────────────
    QScriptEngine parseEngine;
    QScriptValue  parsed = parseEngine.evaluate(
        "(" + QString::fromUtf8(jsonBody.constData(), jsonBody.size()) + ")");
    if (parseEngine.hasUncaughtException())
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));

    QVariantMap body = parsed.toVariant().toMap();

    // ── Required fields ───────────────────────────────────────────────────
    QString outputPath = body.value("output_path").toString().trimmed();
    {
        ValidationResult vr = RequestValidator::validateRequiredField(outputPath, "output_path");
        if (!vr.valid)
            return HttpResult(vr.httpStatus(), stdToQBA(vr.toErrorJson()));
    }

    // ── Optional fields ───────────────────────────────────────────────────
    int  width       = body.contains("width")        ? body.value("width").toInt()        : 0;
    int  height      = body.contains("height")       ? body.value("height").toInt()       : 0;
    int  iraySamples = body.contains("iray_samples") ? body.value("iray_samples").toInt() : 0;
    bool resetMorphs = body.value("reset_morphs").toBool();
    QString camera   = body.value("camera").toString().trimmed();
    QString engine   = body.value("engine").toString().trimmed();

    if ((width > 0) != (height > 0))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "width and height must both be provided or both omitted")));

    if (width < 0 || height < 0)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "width and height must be positive integers")));

    if (!engine.isEmpty()
            && engine != "iray" && engine != "3delight" && engine != "filament")
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "engine must be one of: iray, 3delight, filament")));

    // ── Normalise figure list ─────────────────────────────────────────────
    // Accept {figure, morphs} single-figure shorthand or {figures:[{name,morphs},...]}
    QList<FigureSpec> figureSpecs;

    if (body.contains("figures")) {
        QVariantList figs = body.value("figures").toList();
        for (int i = 0; i < figs.size(); ++i) {
            QVariantMap fig = figs[i].toMap();
            QString name = fig.value("name").toString().trimmed();
            if (name.isEmpty())
                return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD,
                    "figures[" + std::to_string(i) + "].name")));
            FigureSpec spec;
            spec.name   = name;
            spec.morphs = fig.value("morphs").toMap();
            figureSpecs.append(spec);
        }
    } else if (body.contains("figure")) {
        QString name = body.value("figure").toString().trimmed();
        if (!name.isEmpty()) {
            FigureSpec spec;
            spec.name   = name;
            spec.morphs = body.value("morphs").toMap();
            figureSpecs.append(spec);
        }
    }

    // ── Pre-flight: validate figure names against the current scene ───────
    // Runs a minimal DazScript on the main thread before enqueuing so that
    // bad figure references surface immediately (not after render queue wait).
    if (!figureSpecs.isEmpty()) {
        QString validateScript = "(function() {\n  var names = [";
        for (int i = 0; i < figureSpecs.size(); ++i) {
            if (i > 0) validateScript += ",";
            validateScript += "\"";
            validateScript += QString::fromStdString(
                JsonStd::escape(JsonStd::qstrToStd(figureSpecs[i].name)));
            validateScript += "\"";
        }
        validateScript +=
            "];\n"
            "  for (var i = 0; i < names.length; i++) {\n"
            "    if (!Scene.findNodeByLabel(names[i])) return 'NOT_FOUND:' + names[i];\n"
            "  }\n"
            "  return 'OK';\n"
            "})()";

        QScopedPointer<DzScript> valScript(new DzScript());
        valScript->setCode(validateScript);
        if (valScript->execute(QVariantList())) {
            QString valResult = valScript->result().toString();
            if (valResult.startsWith("NOT_FOUND:")) {
                QString missing = valResult.mid(10);
                return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                    "Figure not found in scene: " + JsonStd::qstrToStd(missing))));
            }
        }
        // If the validation script itself fails to parse/execute (e.g. Scene API
        // unavailable at startup), proceed — the render script will surface the
        // error at execution time rather than blocking enqueue.
    }

    // ── Generate and enqueue render job ───────────────────────────────────
    QString renderScript = buildRenderScript(
        outputPath, width, height, camera, engine, iraySamples, resetMorphs, figureSpecs);

    AsyncRequestManager::SubmitResult sr = m_pAsyncMgr->submitRender(renderScript, "rnd");
    if (!sr.accepted)
        return HttpResult(503, stdToQBA(ErrorResponse::build(
            ErrorCode::SERVER_UNAVAILABLE, JsonStd::qstrToStd(sr.error))));

    m_pRenderProgress->setOutputPath(sr.id, outputPath);

    appendLog(QString("[%1] [RENDER QUEUED] output:%2 -> %3")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
        .arg(outputPath).arg(sr.id));

    return buildQueuedResponse(sr.id, sr.submittedAt);
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


void DzScriptServerPane::loadSettings()
{
	QStringList msgs;
	ServerSettings s = m_settingsService.load(msgs);
	for (const QString& msg : msgs)
		appendLog(msg);

	applySettings(s);

	// Persistent metrics — cumulative across restarts
	m_metrics.loadFromSettings();
}

void DzScriptServerPane::applySettings(const ServerSettings& s)
{
	m_sHost                  = s.host;
	m_nPort                  = s.port;
	m_nTimeoutSec            = s.timeoutSec;
	m_bAutoStart             = s.autoStart;
	m_nMaxConcurrentRequests = s.maxConcurrentRequests;
	m_nMaxBodySizeMB         = s.maxBodySizeMB;
	m_nMaxScriptLengthKB     = s.maxScriptLengthKB;

	m_auth.setEnabled(s.authEnabled);

	m_ipWhitelist.setEnabled(s.ipWhitelistEnabled);
	m_ipWhitelist.setWhitelist(s.ipWhitelist);

	m_rateLimiter.setEnabled(s.rateLimitEnabled);
	m_rateLimiter.configure(s.rateLimitMax, s.rateLimitWindow);
}

void DzScriptServerPane::saveSettings()
{
	ServerSettings s;
	s.host                  = m_sHost;
	s.port                  = m_nPort;
	s.timeoutSec            = m_nTimeoutSec;
	s.autoStart             = m_bAutoStart;
	s.maxConcurrentRequests = m_nMaxConcurrentRequests;
	s.maxBodySizeMB         = m_nMaxBodySizeMB;
	s.maxScriptLengthKB     = m_nMaxScriptLengthKB;
	s.authEnabled           = m_auth.isEnabled();
	s.ipWhitelistEnabled    = m_ipWhitelist.isEnabled();
	s.ipWhitelist           = m_ipWhitelist.getWhitelist();
	s.rateLimitEnabled      = m_rateLimiter.isEnabled();
	// Prefer live UI values for rate limit so the user sees what was saved.
	s.rateLimitMax    = m_pRateLimitMaxSpin    ? m_pRateLimitMaxSpin->value()
	                                           : ServerConfig::DEFAULT_RATE_LIMIT_MAX;
	s.rateLimitWindow = m_pRateLimitWindowSpin ? m_pRateLimitWindowSpin->value()
	                                           : ServerConfig::DEFAULT_RATE_LIMIT_WINDOW;

	m_settingsService.save(s);
	m_metrics.saveToSettings();
}


void DzScriptServerPane::onCopyTokenClicked()
{
	QClipboard* clipboard = QApplication::clipboard();
	if (clipboard) {
		clipboard->setText(m_auth.getToken());
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
		QStringList msgs;
		if (m_auth.loadOrGenerateToken(msgs)) {
			m_pTokenEdit->setText(m_auth.getToken());
			appendLog("New API token generated");
		}
		foreach (const QString& msg, msgs)
			appendLog(msg);
	}
}

void DzScriptServerPane::onAuthEnabledChanged(int state)
{
	m_auth.setEnabled(state == Qt::Checked);
	saveSettings();

	if (!m_auth.isEnabled() && m_bRunning) {
		appendLog("[WARN] Authentication disabled - anyone can execute scripts!");
	}
}

void DzScriptServerPane::onClearLogClicked()
{
	if (m_pLogView) {
		m_pLogView->clear();
	}
}

void DzScriptServerPane::onIpWhitelistEnabledChanged(int state)
{
	m_ipWhitelist.setEnabled(state == Qt::Checked);
	saveSettings();

	if (m_ipWhitelist.isEnabled() && m_bRunning) {
		appendLog("[INFO] IP whitelist enabled - only configured IPs allowed");
	}
}

void DzScriptServerPane::onRateLimitEnabledChanged(int state)
{
	m_rateLimiter.setEnabled(state == Qt::Checked);
	saveSettings();

	if (m_rateLimiter.isEnabled() && m_bRunning) {
		appendLog(QString("[INFO] Rate limiting enabled - max %1 requests per %2 seconds")
			.arg(m_pRateLimitMaxSpin ? m_pRateLimitMaxSpin->value() : ServerConfig::DEFAULT_RATE_LIMIT_MAX)
			.arg(m_pRateLimitWindowSpin ? m_pRateLimitWindowSpin->value() : ServerConfig::DEFAULT_RATE_LIMIT_WINDOW));
	}
}

void DzScriptServerPane::onAutoStartChanged(int state)
{
	m_bAutoStart = (state == Qt::Checked);
	saveSettings();
}

void DzScriptServerPane::updateActiveRequestsLabel()
{
	if (m_pActiveRequestsLabel) {
		m_pActiveRequestsLabel->setText(tr("Active Requests: %1 / %2")
			.arg((int)m_nActiveRequests)
			.arg(m_nMaxConcurrentRequests));
	}
}

void DzScriptServerPane::updateEventClientsLabel()
{
	if (m_pEventClientsLabel) {
		int count = m_pEventBroker ? m_pEventBroker->subscriberCount() : 0;
		m_pEventClientsLabel->setText(tr("Event Clients: %1").arg(count));
	}
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
	s += "}";
	return s;
}

std::string DzScriptServerPane::getMetricsJson() const
{
	// Build with std::string only — called from httplib worker threads where Qt string ops are unsafe.
	int total      = m_metrics.getTotalRequests();
	int successful = m_metrics.getSuccessfulRequests();
	int failed     = m_metrics.getFailedRequests();
	int authFail   = m_metrics.getAuthFailures();
	int active     = (int)m_nActiveRequests;
	long long uptime = (long long)m_metrics.getUptimeSeconds();
	double rate    = total > 0 ? (double)successful / total * 100.0 : 0.0;

	char rateBuf[32];
	std::snprintf(rateBuf, sizeof(rateBuf), "%.15g", rate);

	std::string s = "{\"total_requests\":";
	s += std::to_string(total);
	s += ",\"successful_requests\":";
	s += std::to_string(successful);
	s += ",\"failed_requests\":";
	s += std::to_string(failed);
	s += ",\"auth_failures\":";
	s += std::to_string(authFail);
	s += ",\"active_requests\":";
	s += std::to_string(active);
	s += ",\"uptime_seconds\":";
	s += std::to_string(uptime);
	s += ",\"success_rate_percent\":";
	s += rateBuf;
	s += "}";
	return s;
}

// ─── Async Execution (main thread) ───────────────────────────────────────────

// Called on the main thread via Qt::QueuedConnection (connected to
// AsyncRequestManager::requestEnqueued signal) and self-reposted after each
// execution completes to drain the queue.
//
// Blocks the main thread (Qt event loop) for the full duration of each script.
// That is intentional — DAZ Studio's DzScript API is not thread-safe.  HTTP
// threads serving status/result queries go directly to AsyncRequestManager's
// mutex-protected map and are unaffected.
void DzScriptServerPane::processNextAsyncRequest()
{
	QString id, scriptText;
	QVariantMap args;
	if (!m_pAsyncMgr->dequeueNext(id, scriptText, args)) return;

	// Request may have been cancelled while queued
	if (m_pAsyncMgr->isCancelRequested(id)) {
		m_pAsyncMgr->markCancelled(id, "Cancelled before execution started");
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
	m_aCapturedLogLines.clear();
	m_bCapturingLog = true;
	connect(dzApp, SIGNAL(debugMsg(const QString&)),
	        this,  SLOT(onMessagePosted(const QString&)),
	        Qt::DirectConnection);

	QScopedPointer<DzScript> script(new DzScript());
	script->setCode(scriptText);

	QVariantList execArgs;
	execArgs << QVariant(args);

	bool     executed = script->execute(execArgs);
	QVariant scriptResult;
	QString  errorMsg;
	if (executed) {
		scriptResult = script->result();
	} else {
		errorMsg    = script->errorMessage();
		int errLine = script->errorLine();
		if (errLine > 0)
			errorMsg = QString("Line %1: %2").arg(errLine).arg(errorMsg);
	}
	QStringList capturedOutput = m_aCapturedLogLines;

	script.reset();  // Destroy script before disconnecting the signal
	disconnect(dzApp, SIGNAL(debugMsg(const QString&)),
	           this,  SLOT(onMessagePosted(const QString&)));
	m_bCapturingLog = false;

	int durationMs = wallClock.msecsTo(QTime::currentTime());

	bool wasCancelled = false;
	m_pAsyncMgr->markCompleted(id, executed, scriptResult, capturedOutput, errorMsg, wasCancelled);
	m_pAsyncMgr->clearCurrent();

	if (isRender && m_pRenderProgress) {
		if (executed && !wasCancelled)
			m_pRenderProgress->notifyCompleted(id, durationMs);
		else
			m_pRenderProgress->notifyFailed(id, errorMsg, durationMs);
	}

	m_metrics.recordRequest(executed && !wasCancelled);

	appendLog(QString("[%1] [ASYNC] [%2] [%3ms] %4")
		.arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
		.arg(wasCancelled ? "CANCEL" : (executed ? "OK" : "ERR"))
		.arg(durationMs)
		.arg(id));

	// Drain the queue
	QMetaObject::invokeMethod(this, "processNextAsyncRequest", Qt::QueuedConnection);
}

// Removes completed/failed/cancelled requests older than 1 hour.
// Fired by m_pCleanupTimer every 5 minutes on the main thread.
void DzScriptServerPane::cleanupExpiredRequests()
{
	int removed = m_pAsyncMgr->cleanupExpired();
	if (removed > 0) {
		appendLog(QString("[INFO] Async cleanup: removed %1 expired request(s)").arg(removed));
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

#include "moc_DzScriptServerPane.cpp"
