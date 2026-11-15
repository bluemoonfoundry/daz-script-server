// Include httplib ONLY here — it pulls in winsock2.h and Windows macros.
// CPPHTTPLIB_NO_COMPRESS is set via target_compile_definitions in CMakeLists.txt.
#include "httplib.h"
#include <ctime>
#include <vector>

#include "DzScriptServerPane.h"
#include "JsonBuilder.h"
#include "JsonStd.h"
#include "ErrorResponse.h"
#include "IdempotencyCache.h"
#include "ArtifactFile.h"
#include "SecureRandom.h"
#include "RequestValidator.h"
#include "common_version.h"
#include "GeometryExport.h"

#include <QtCore/quuid.h>
#include <dzapp.h>
#include <dzscript.h>
#include <dzscene.h>
#include <dzrendermgr.h>
#include <dzrenderer.h>
#include <dzprogress.h>

#if DAZ_SDK_MAJOR_VERSION >= 6
// dzscript.h only forward-declares QJSValue on SDK6 (DzScript::result()
// returns one there, replacing SDK4's QScriptValue); pull in the real type.
#include <QtQml/qjsvalue.h>
#include <QtCore/qjsonarray.h>
#endif

#include <QtCore/qmetaobject.h>
#include <QtCore/qcryptographichash.h>
#include <QtCore/qsettings.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qfile.h>
#include <QtCore/qfileinfo.h>
#include <QtCore/qdir.h>
#include <QtCore/qmap.h>
#include <QtCore/qmutex.h>
#if DAZ_SDK_MAJOR_VERSION >= 6
// QRegExp was removed from Qt6 Core (Qt5Compat provides it under a
// different include path); QRegularExpression is available unchanged
// since Qt 5.0, so use it instead of pulling in the compat module.
#include <QtCore/qregularexpression.h>
#else
#include <QtCore/qregexp.h>
#endif
#include <QtCore/qscopedpointer.h>
#if DAZ_SDK_MAJOR_VERSION >= 6
// QClipboard stays in QtGui; the rest moved to QtWidgets in Qt5/6.
#include <QtGui/qclipboard.h>
#include <QtWidgets/qboxlayout.h>
#include <QtWidgets/qformlayout.h>
#include <QtWidgets/qgroupbox.h>
#include <QtWidgets/qapplication.h>
#include <QtWidgets/qmessagebox.h>
#include <QtWidgets/qscrollarea.h>
#else
#include <QtGui/qboxlayout.h>
#include <QtGui/qformlayout.h>
#include <QtGui/qgroupbox.h>
#include <QtGui/qclipboard.h>
#include <QtGui/qapplication.h>
#include <QtGui/qmessagebox.h>
#include <QtGui/qscrollarea.h>
#endif

// ─── DzScript lifetime ─────────────────────────────────────────────────────────
// On SDK6, DzScript's destructor is protected — direct `delete` no longer
// compiles, scripts must be disposed via QObject::deleteLater() instead.
// SDK4 keeps a public destructor, so this stays a plain `delete` there.
struct DzScriptDeleter {
#if DAZ_SDK_MAJOR_VERSION >= 6
	static void cleanup(DzScript* p) { if (p) p->deleteLater(); }
#else
	static void cleanup(DzScript* p) { delete p; }
#endif
};

// ─── print() output capture ────────────────────────────────────────────────────
// dzApp::debugMsg(QString) is deprecated on SDK6 and no longer actually
// fires (verified empirically — print() output still reaches DAZ Studio's own
// log file, but not this signal); use the replacement debugMessage(message,
// category) instead. onMessagePosted(const QString&) still works as the slot
// for either signal — Qt allows connecting a slot with fewer parameters than
// the signal it's connected to, so the extra category argument is just
// dropped on SDK6.
#if DAZ_SDK_MAJOR_VERSION >= 6
#define DSS_DEBUG_SIGNAL SIGNAL(debugMessage(const QString&, const QString&))
#else
#define DSS_DEBUG_SIGNAL SIGNAL(debugMsg(const QString&))
#endif

// ─── DzScript execution ────────────────────────────────────────────────────────
// Runs `script`'s already-loaded code (via setCode()/loadFromFile()) with
// `argsMap` exposed to the script as getArguments()[0], per the documented
// args contract.
//
// SDK4: DzScript::execute(args) + result() works as documented.
// SDK6 (BETA): execute()+result() does not capture a completion value at all
// (verified empirically — even `1+1` returns an empty result) and dzApp's
// debugMsg signal no longer fires (replaced by debugMessage(msg, category),
// handled separately in the caller). So on SDK6 this re-evaluates the
// script's own source via evaluate() instead, which does return a usable
// value, with getArguments() shimmed in as a prepended JS function since
// evaluate() has no args parameter of its own.
struct ScriptRunResult {
	bool        success = false;
	QVariant    result;
	QString     errorMessage;
	int         errorLine = 0;
	QStringList output;   // SDK6 only — see below; SDK4 still uses the debugMsg signal capture
};

static ScriptRunResult runDazScript(
	DzScript* script,
	const QVariantMap& argsMap,
	const QString& scriptFilename)
{
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
	, m_nStaleJobTimeoutMin(ServerConfig::ASYNC_STALE_RUNNING_TIMEOUT_MIN)
	, m_rateLimiter(ServerConfig::DEFAULT_RATE_LIMIT_MAX, ServerConfig::DEFAULT_RATE_LIMIT_WINDOW)
	, m_pAsyncMgr(nullptr)
	, m_pCleanupTimer(nullptr)
	, m_pEventBroker(nullptr)
	, m_pRenderProgress(nullptr)
	, m_pEventClientsLabel(nullptr)
	, m_pLogView(nullptr)
	, m_pPersistentScript(nullptr)
{
	// Register return type for BlockingQueuedConnection on execute/register handlers.
	qRegisterMetaType<HttpResult>("HttpResult");

	// m_pPersistentScript is lazily created on first use (see
	// ensurePersistentScript()) rather than here — this constructor runs very
	// early during DAZ Studio startup (panes get restored before the app is
	// fully initialized), and DzScript may depend on subsystems that aren't
	// ready yet at this point.

	// Load settings and token
	loadSettings();

	QStringList tokenMsgs;
	if (!m_auth.loadOrGenerateToken(tokenMsgs)) {
		// Crypto API unavailable — log will be empty at this point, messages shown later
	}
	for (const QString& msg : tokenMsgs)
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

	m_pStaleTimeoutSpin = new QSpinBox(this);
	m_pStaleTimeoutSpin->setRange(ServerConfig::ASYNC_STALE_RUNNING_TIMEOUT_MIN_MIN,
	                              ServerConfig::ASYNC_STALE_RUNNING_TIMEOUT_MAX_MIN);
	m_pStaleTimeoutSpin->setValue(m_nStaleJobTimeoutMin);
	m_pStaleTimeoutSpin->setSuffix(tr(" min"));
	m_pStaleTimeoutSpin->setToolTip(tr(
		"An async job still running after this long is reported as \"stale\" "
		"(usually DAZ Studio is blocked behind a dialog). Raise it for long "
		"renders. Checked every %1 minutes.").arg(ServerConfig::ASYNC_CLEANUP_INTERVAL_MIN));
	limitsFormLayout->addRow(tr("Stuck Job Timeout:"), m_pStaleTimeoutSpin);

	QLabel* staleHint = new QLabel(
		tr("Applies immediately; raise it if long renders get marked stale"), this);
	staleHint->setStyleSheet("QLabel { color: gray; font-size: 9pt; }");
	limitsFormLayout->addRow(staleHint);

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
	connect(m_pStaleTimeoutSpin, SIGNAL(valueChanged(int)), this, SLOT(onStaleTimeoutChanged(int)));

	updateUI();

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

	// Cap request bodies while httplib is still reading them. Without this,
	// httplib buffers up to its 100 MB compile-time default on every route before
	// any middleware runs. The spin box is disabled while the server is running,
	// so the value can't change under the worker threads.
	const size_t maxBodyBytes = static_cast<size_t>(m_nMaxBodySizeMB) * 1024 * 1024;
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
	m_pEventBroker->setRevisionCounter(&m_sceneRevision);
	m_pEventBroker->start();

	m_pRenderProgress = new RenderProgressBroker();

	// Prime the snapshot GET /capabilities serves while the main thread is busy.
	refreshCapabilitiesSnapshot();

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

	// 2. Signal the HTTP server to shut down: closes the listening socket so
	//    the accept loop in ServerListenThread::run() unblocks and returns,
	//    and sets is_shutting_down = true so chunked write loops exit on
	//    their next iteration. Do NOT delete m_pServer yet — run() is still
	//    executing on m_pServerThread and holds a raw pointer to it; deleting
	//    it now would be a use-after-free race with that thread.
	if (m_pServer) {
		m_pServer->stop();
	}

	// 3. Join the listen thread before touching m_pServer again. httplib's
	//    ThreadPool::shutdown() joins every request-handler thread before
	//    listen() returns, so by the time wait() completes ALL SSE
	//    resource-releaser lambdas have already run.
	if (m_pServerThread) {
		if (!m_pServerThread->wait(ServerConfig::SERVER_THREAD_STOP_TIMEOUT_MS)) {
			appendLog("[WARN] Server thread did not stop within timeout; forcing termination.");
			m_pServerThread->terminate();
			m_pServerThread->wait(1000);
		}
		delete m_pServerThread;
		m_pServerThread = nullptr;
	}

	// Now that run() has returned (or the thread was forcibly killed), it's
	// safe to free the Server object.
	if (m_pServer) {
		delete m_pServer;
		m_pServer = nullptr;
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

static HttpContext toContext(const httplib::Request& req)
{
	HttpContext ctx;
	ctx.body       = req.body;
	ctx.remoteAddr = req.remote_addr.empty() ? "unknown" : req.remote_addr;
	if (req.matches.size() > 1)
		ctx.urlMatch = req.matches[1].str();
	ctx.headers["x-api-token"]  = req.get_header_value("X-API-Token");
	ctx.headers["authorization"] = req.get_header_value("Authorization");
	ctx.headers["idempotency-key"]  = req.get_header_value("Idempotency-Key");
	ctx.headers["x-correlation-id"] = req.get_header_value("X-Correlation-Id");
	for (httplib::Params::const_iterator it = req.params.begin();
	     it != req.params.end(); ++it)
		ctx.queryParams[it->first] = it->second;
	return ctx;
}

static void applyContext(const HttpContext& ctx, httplib::Response& res)
{
	res.status = ctx.responseStatus;
	if (!ctx.responseBody.empty())
		res.set_content(ctx.responseBody, ctx.responseContentType);
	for (std::map<std::string, std::string>::const_iterator it = ctx.responseHeaders.begin();
	     it != ctx.responseHeaders.end(); ++it)
		res.set_header(it->first.c_str(), it->second.c_str());
}

// Insert extra members (",\"k\":v,...", leading comma included) before the
// closing brace of a JSON object body. Non-object bodies are returned as is.
static std::string stampJsonObject(const std::string& body, const std::string& members)
{
	if (members.empty() || body.empty() || body[0] != '{') return body;
	const size_t close = body.find_last_of('}');
	if (close == std::string::npos) return body;
	const bool emptyObject = body.find_first_not_of(" \t\r\n", 1) == close;
	return body.substr(0, close) + (emptyObject ? members.substr(1) : members) + body.substr(close);
}

// Releases an in-flight idempotency record if the handler exits abnormally
// (exception), so the key isn't wedged as IN_FLIGHT until the TTL expires.
struct IdempotencyGuard {
	IdempotencyCache& cache;
	const QByteArray& key;
	bool              done;
	IdempotencyGuard(IdempotencyCache& c, const QByteArray& k) : cache(c), key(k), done(false) {}
	~IdempotencyGuard() { if (!done && !key.isEmpty()) cache.complete(key, 500, QByteArray()); }
private:
	IdempotencyGuard(const IdempotencyGuard&);
	IdempotencyGuard& operator=(const IdempotencyGuard&);
};

void DzScriptServerPane::runJobRoute(const httplib::Request& req, httplib::Response& res,
                                     IRequestHandler* handler, bool idempotent)
{
	HttpContext ctx = toContext(req);
	if (!m_pWriteChain->run(ctx)) {
		applyContext(ctx, res);
		return;
	}

	// ── X-Correlation-Id: client-supplied, or generated so every job has one.
	const std::string corrHeader = ctx.getHeader("x-correlation-id");
	if (!corrHeader.empty()) {
		if (!IdempotencyCache::isValidKey(QByteArray(corrHeader.c_str(), (int)corrHeader.size()))) {
			ctx.respond(400, ErrorResponse::build(ErrorCode::INVALID_FIELD,
				"X-Correlation-Id must be 1-255 printable ASCII characters without spaces"));
			applyContext(ctx, res);
			return;
		}
		ctx.correlationId = corrHeader;
	} else {
		const QByteArray gen = ("cor-" + MetricsCollector::generateRequestId()).toLatin1();
		ctx.correlationId.assign(gen.constData(), gen.size());
	}
	ctx.setHeader("X-Correlation-Id", ctx.correlationId);

	// From here on every response (success or error) carries the identity
	// fields. Requests rejected above, before a correlation ID exists, get only
	// the X-Server-Instance-Id header from the post-routing hook.
	const QByteArray instanceId = m_serverInstanceId;
	auto stampIdentity = [&]() {
		std::string members = ",\"server_instance_id\":\"";
		members.append(instanceId.constData(), instanceId.size());
		members += "\",\"correlation_id\":\"" + JsonStd::escape(ctx.correlationId) + "\"";
		members += ",\"scene_revision\":" + std::to_string(sceneRevision());
		ctx.responseBody = stampJsonObject(ctx.responseBody, members);
	};

	// ── Idempotency-Key: replay the first response instead of running twice.
	QByteArray scoped;
	const std::string keyHeader = idempotent ? ctx.getHeader("idempotency-key") : std::string();
	if (!keyHeader.empty()) {
		const QByteArray key(keyHeader.c_str(), (int)keyHeader.size());
		if (!IdempotencyCache::isValidKey(key)) {
			ctx.respond(400, ErrorResponse::build(ErrorCode::INVALID_FIELD,
				"Idempotency-Key must be 1-255 printable ASCII characters without spaces"));
			stampIdentity();
			applyContext(ctx, res);
			return;
		}
		scoped = IdempotencyCache::scopedKey(
			QByteArray(req.method.c_str(), (int)req.method.size()),
			QByteArray(req.path.c_str(), (int)req.path.size()), key);
		const QByteArray fp = IdempotencyCache::fingerprint(
			scoped, QByteArray(ctx.body.c_str(), (int)ctx.body.size()));

		int        replayStatus = 0;
		QByteArray replayBody;
		switch (m_idempotency.begin(scoped, fp, replayStatus, replayBody)) {
		case IdempotencyCache::REPLAY: {
			// The stored body is returned as is: it already carries the
			// ORIGINAL correlation_id and identity. Drop this request's
			// generated header ID so it can't contradict the body (the
			// post-routing hook still echoes a client-supplied value).
			ctx.respond(replayStatus, stampJsonObject(
				std::string(replayBody.constData(), replayBody.size()),
				",\"idempotent_replay\":true"));
			ctx.setHeader("Idempotent-Replayed", "true");
			ctx.responseHeaders.erase("X-Correlation-Id");
			applyContext(ctx, res);
			return;
		}
		case IdempotencyCache::IN_FLIGHT:
			ctx.respond(409, ErrorResponse::build(ErrorCode::IDEMPOTENCY_KEY_IN_FLIGHT));
			ctx.setHeader("Retry-After", "1");
			stampIdentity();
			applyContext(ctx, res);
			return;
		case IdempotencyCache::MISMATCH:
			ctx.respond(422, ErrorResponse::build(ErrorCode::IDEMPOTENCY_KEY_REUSED));
			stampIdentity();
			applyContext(ctx, res);
			return;
		case IdempotencyCache::PROCEED:
			break;
		}
	}

	IdempotencyGuard guard(m_idempotency, scoped);
	handler->handle(ctx);

	stampIdentity();

	if (!scoped.isEmpty()) {
		m_idempotency.complete(scoped, ctx.responseStatus,
			QByteArray(ctx.responseBody.c_str(), (int)ctx.responseBody.size()));
		guard.done = true;
	}

	applyContext(ctx, res);
}

// ─── Artifacts (GET /artifacts/...) ──────────────────────────────────────────
//
// Run on httplib worker threads: they read a mutex-protected copy of the job's
// output manifest and use C stdio for file access (ArtifactFile), never DAZ or
// GUI objects. URL segments are IDs, never paths: the only file that can be
// opened is one the job itself declared.

static void respondError(httplib::Response& res, ErrorCode code, const std::string& detail = "")
{
	res.status = ErrorResponse::httpStatus(code);
	res.set_content(ErrorResponse::build(code, detail), "application/json");
}

static bool artifactIdsValid(const httplib::Request& req, httplib::Response& res)
{
	static const char* const kNames[] = { "", "job_id", "artifact_id" };
	for (size_t i = 1; i < req.matches.size() && i < 3; ++i) {
		const std::string v = req.matches[i].str();
		if (!ArtifactFile::isValidId(v.c_str(), v.size())) {
			respondError(res, ErrorCode::INVALID_FIELD,
				std::string(kNames[i]) + " must be 1-64 characters of A-Z, a-z, 0-9, '-' or '_'");
			return false;
		}
	}
	return true;
}

// GET /artifacts/:job_id — the job's declared outputs plus file metadata.
static void listArtifacts(AsyncRequestManager& mgr, const httplib::Request& req,
                          httplib::Response& res)
{
	if (!artifactIdsValid(req, res)) return;
	const std::string jobId = req.matches[1].str();

	QVariantList entries;
	QString      status;
	if (!mgr.artifactManifest(jobId, entries, status)) {
		respondError(res, ErrorCode::REQUEST_NOT_FOUND, jobId);
		return;
	}

	QVariantList artifacts;
	for (int i = 0; i < entries.size(); ++i) {
		QVariantMap entry = entries[i].toMap();
		const QString path = entry.value("path").toString();
		const qint64  size = ArtifactFile::sizeOf(path);
		entry.insert("available", size >= 0);
		entry.insert("size", size >= 0 ? QVariant(size) : QVariant());
		entry.insert("content_type", QString::fromLatin1(ArtifactFile::contentTypeFor(path)));
		entry.insert("filename", ArtifactFile::baseName(path));
		artifacts.append(entry);
	}

	QVariantMap body;
	body.insert("success", true);
	body.insert("request_id", QString::fromStdString(jobId));
	body.insert("status", status);
	body.insert("count", artifacts.size());
	body.insert("artifacts", artifacts);
	res.status = 200;
	res.set_content(JsonStd::variantToJson(QVariant(body)), "application/json");
}

// GET /artifacts/:job_id/:artifact_id — stream one declared output. httplib
// answers Range requests (206 / 416) and HEAD from the sized content provider.
static void serveArtifact(AsyncRequestManager& mgr, const httplib::Request& req,
                          httplib::Response& res)
{
	if (!artifactIdsValid(req, res)) return;
	const std::string jobId      = req.matches[1].str();
	const std::string artifactId = req.matches[2].str();

	QString path;
	switch (mgr.findArtifact(jobId, artifactId, path)) {
	case AsyncRequestManager::ARTIFACT_JOB_NOT_FOUND:
		respondError(res, ErrorCode::REQUEST_NOT_FOUND, jobId);
		return;
	case AsyncRequestManager::ARTIFACT_NOT_DECLARED:
		respondError(res, ErrorCode::ARTIFACT_NOT_FOUND, jobId + "/" + artifactId);
		return;
	case AsyncRequestManager::ARTIFACT_FOUND:
		break;
	}

	FILE*  file = 0;
	qint64 size = 0;
	switch (ArtifactFile::openForRead(path, &file, &size)) {
	case ArtifactFile::OPEN_OK:
		break;
	case ArtifactFile::OPEN_PATH_REJECTED:
		respondError(res, ErrorCode::ARTIFACT_UNAVAILABLE, "declared path is not an absolute file path");
		return;
	case ArtifactFile::OPEN_NOT_REGULAR:
		respondError(res, ErrorCode::ARTIFACT_UNAVAILABLE, "declared path is not a regular file");
		return;
	case ArtifactFile::OPEN_MISSING:
	default:
		respondError(res, ErrorCode::ARTIFACT_UNAVAILABLE, "declared file does not exist or cannot be read");
		return;
	}

	// Leave res.status unset: httplib then picks 200, or 206 for a Range
	// request (and 416 for an unsatisfiable one). An explicit 200 would make
	// it ignore the Range header and send the whole file.
	const QByteArray disposition = ArtifactFile::contentDisposition(path);
	res.set_header("Accept-Ranges", "bytes");
	res.set_header("Content-Disposition", disposition.constData());
	res.set_header("Cache-Control", "private, no-store");
	res.set_header("X-Content-Type-Options", "nosniff");
	res.set_content_provider(
		static_cast<size_t>(size), ArtifactFile::contentTypeFor(path),
		[file](size_t offset, size_t length, httplib::DataSink& sink) {
			if (!ArtifactFile::seek(file, static_cast<qint64>(offset))) return false;
			char buf[64 * 1024];
			while (length > 0) {
				const size_t want = length < sizeof(buf) ? length : sizeof(buf);
				const size_t got  = std::fread(buf, 1, want, file);
				if (got == 0) return false;   // file shrank or read error
				if (!sink.write(buf, got)) return false;
				length -= got;
			}
			return true;
		},
		[file](bool) { std::fclose(file); });
}

// ─── Route setup ──────────────────────────────────────────────────────────────
//
// THREADING RULE: httplib invokes these handlers on raw std::threads (not QThreads).
// Sync handlers cross to the main thread with BlockingQueuedConnection. On
// Studio 6, async script enqueue handlers may build local reentrant Qt Core
// values and call mutex-protected services; Studio 4 crosses to the main thread
// because its JSON parser uses QScriptEngine. Execution later reaches the main
// thread through a queued wake-up. No worker may touch GUI, DzScript, DAZ SDK,
// or shared mutable pane state.

void DzScriptServerPane::setupRoutes()
{
	// ── Middleware chains ─────────────────────────────────────────────────────
	//
	// Every authenticated route runs one of these two chains, so the IP whitelist
	// always runs before auth. tests/test_route_security.py enforces this.
	//
	// Write chain: every POST/DELETE route (anything that executes, mutates or
	// writes to disk). BodySizeMiddleware is defence in depth: httplib's
	// set_payload_max_length (startServer) already stops oversized bodies while
	// they are being read.
	m_pWriteChain.reset(new MiddlewareChain());
	m_pWriteChain->add(new IPWhitelistMiddleware(m_ipWhitelist, this));
	m_pWriteChain->add(new RateLimitMiddleware(m_rateLimiter, this));
	m_pWriteChain->add(new BodySizeMiddleware(m_nMaxBodySizeMB));
	m_pWriteChain->add(new AuthMiddleware(m_auth, m_metrics, this));

	// Read chain: GET polling and SSE routes. Not rate limited, because clients
	// poll /requests/:id/status in a loop and a 60 req/60s window would throttle
	// a single well-behaved job watcher.
	m_pReadChain.reset(new MiddlewareChain());
	m_pReadChain->add(new IPWhitelistMiddleware(m_ipWhitelist, this));
	m_pReadChain->add(new AuthMiddleware(m_auth, m_metrics, this));

	// ── Request handlers ──────────────────────────────────────────────────────
	m_pStatusHandler.reset(new StatusHandler(DZSRV_VERSION_STR, this));
	m_pHealthHandler.reset(new HealthHandler(this));
	m_pMetricsHandler.reset(new MetricsHandler(this));
	m_pCapabilitiesHandler.reset(new CapabilitiesHandler(this));
	m_pExecuteHandler.reset(new ExecuteScriptHandler(this));
	m_pRegisterHandler.reset(new ScriptRegisterHandler(this));
	m_pScriptListHandler.reset(new ScriptListHandler(this));
	m_pScriptDeleteHandler.reset(new ScriptDeleteHandler(this));
	m_pScriptExecHandler.reset(new ScriptExecuteHandler(this));
	// Snapshot the GUI-owned limit before httplib starts its worker threads.
	// The corresponding control is disabled while the server is running.
	m_pAsyncExecHandler.reset(new AsyncExecuteHandler(this, m_nMaxScriptLengthKB));
	m_pAsyncScriptHandler.reset(new AsyncScriptHandler(this));
	m_pAsyncStatusHandler.reset(new AsyncStatusHandler(this));
	m_pAsyncResultHandler.reset(new AsyncResultHandler(this));
	m_pAsyncCancelHandler.reset(new AsyncCancelHandler(this));
	m_pAsyncListHandler.reset(new AsyncListHandler(this));
	m_pRenderHandler.reset(new RenderHandler(this));
	m_pRenderBatchHandler.reset(new RenderBatchHandler(this));
	m_pRenderAnimationHandler.reset(new RenderAnimationHandler(this));
	m_pRenderCancelHandler.reset(new RenderCancelHandler(this));
	m_pSaveCopyHandler.reset(new SaveCopyHandler(this));
	m_pGeometryFramesHandler.reset(new GeometryFramesHandler());

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

	m_pServer->Get("/capabilities", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pReadChain->run(ctx)) m_pCapabilitiesHandler->handle(ctx);
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

		// Sync execution is not idempotent: a retry runs the script again.
		// Clients that need retry safety use /execute/async + Idempotency-Key.
		runJobRoute(req, res, m_pExecuteHandler.get(), false);
		QMetaObject::invokeMethod(this, "updateActiveRequestsLabel", Qt::QueuedConnection);
	});

	m_pServer->Post("/scripts/register", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pRegisterHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/scripts", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pReadChain->run(ctx)) m_pScriptListHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Delete("/scripts/([^/]+)", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pScriptDeleteHandler->handle(ctx);
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
		runJobRoute(req, res, m_pScriptExecHandler.get(), false);
		QMetaObject::invokeMethod(this, "updateActiveRequestsLabel", Qt::QueuedConnection);
	});

	// ── Async endpoints ──────────────────────────────────────────────────────

	m_pServer->Post("/execute/async", [this](const httplib::Request& req, httplib::Response& res) {
		runJobRoute(req, res, m_pAsyncExecHandler.get(), true);
	});

	m_pServer->Post("/scripts/([^/]+)/async", [this](const httplib::Request& req, httplib::Response& res) {
		runJobRoute(req, res, m_pAsyncScriptHandler.get(), true);
	});

	m_pServer->Get("/requests/([^/]+)/status", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pReadChain->run(ctx)) m_pAsyncStatusHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/requests/([^/]+)/result", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pReadChain->run(ctx)) m_pAsyncResultHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Delete("/requests/([^/]+)", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pAsyncCancelHandler->handle(ctx);
		applyContext(ctx, res);
	});

	m_pServer->Get("/requests", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pReadChain->run(ctx)) m_pAsyncListHandler->handle(ctx);
		applyContext(ctx, res);
	});

	// GET /artifacts/:job_id and GET /artifacts/:job_id/:artifact_id
	//
	// Read chain (IP whitelist -> auth), like the other polling GETs: a client
	// fetching a large file in Range chunks must not trip the rate limiter.
	// Downloads only serve files in the job's output manifest; see
	// listArtifacts()/serveArtifact() above.
	m_pServer->Get("/artifacts/([^/]+)", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (!m_pReadChain->run(ctx)) { applyContext(ctx, res); return; }
		listArtifacts(*m_pAsyncMgr, req, res);
	});

	m_pServer->Get("/artifacts/([^/]+)/([^/]+)", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (!m_pReadChain->run(ctx)) { applyContext(ctx, res); return; }
		serveArtifact(*m_pAsyncMgr, req, res);
	});

	// ── Render endpoints ──────────────────────────────────────────────────────

	m_pServer->Post("/render", [this](const httplib::Request& req, httplib::Response& res) {
		runJobRoute(req, res, m_pRenderHandler.get(), true);
	});

	m_pServer->Post("/render/batch", [this](const httplib::Request& req, httplib::Response& res) {
		runJobRoute(req, res, m_pRenderBatchHandler.get(), true);
	});

	m_pServer->Post("/render/animation", [this](const httplib::Request& req, httplib::Response& res) {
		runJobRoute(req, res, m_pRenderAnimationHandler.get(), true);
	});

	m_pServer->Post("/render/([^/]+)/cancel", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pRenderCancelHandler->handle(ctx);
		applyContext(ctx, res);
	});

	// ── Scene I/O endpoints ───────────────────────────────────────────────────

	m_pServer->Post("/scene/save-copy", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pSaveCopyHandler->handle(ctx);
		applyContext(ctx, res);
	});

	// Fork: deformed figure vertices for a frame list as binary (GeometryExport.h)
	m_pServer->Post("/geometry/frames", [this](const httplib::Request& req, httplib::Response& res) {
		auto ctx = toContext(req);
		if (m_pWriteChain->run(ctx)) m_pGeometryFramesHandler->handle(ctx);
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
			if (!m_pReadChain->run(ctx)) {
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
			if (!m_pReadChain->run(ctx)) {
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

	{
		QMutexLocker lock(&m_pluginRoutesMutex);
		bool found = false;
		for (int i = 0; i < m_pluginRoutes.size(); ++i) {
			if (m_pluginRoutes[i].method == m && m_pluginRoutes[i].path == path) {
				m_pluginRoutes[i] = r;
				found = true;
				break;
			}
		}
		if (!found)
			m_pluginRoutes.append(r);
	}
	appendLog(QString("[INFO] Plugin route registered: %1 %2").arg(m).arg(path));
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

// Match a path-pattern (e.g. "/export/usd/:id") against a concrete path.
// Fills `params` with captured segment values keyed by the param name (no colon).
// Returns true on match.  Both arguments must start with '/'.
static bool matchPluginPath(const QString& pattern, const QString& path,
                             QMap<QString, QString>& params)
{
	const QStringList patParts  = pattern.split('/');
	const QStringList pathParts = path.split('/');
	if (patParts.size() != pathParts.size()) return false;
	params.clear();
	for (int i = 0; i < patParts.size(); ++i) {
		if (patParts[i].startsWith(':'))
			params[patParts[i].mid(1)] = pathParts[i];
		else if (patParts[i] != pathParts[i])
			return false;
	}
	return true;
}

void DzScriptServerPane::applyPluginRoutes()
{
	// Register a single catch-all handler per HTTP method.  Each handler scans
	// m_pluginRoutes at request time (mutex-protected) so that routes registered
	// after server start — and routes that change dynamically — are always
	// visible without ever touching httplib's handler vectors post-startup.
	// This avoids the data race that would occur if we called m_pServer->Get/Post
	// from registerPluginRoute() while the listen thread is dispatching requests.

	auto makeHandler = [this](const QString& method) {
		return [this, method](const httplib::Request& req, httplib::Response& res) {
			const QString qpath = QString::fromStdString(req.path);
			QMap<QString, QString> params;

			QPointer<QObject> receiver;
			QByteArray        slotBytes;
			bool              found = false;
			{
				QMutexLocker lock(&m_pluginRoutesMutex);
				for (int i = 0; i < m_pluginRoutes.size(); ++i) {
					const PluginRoute& r = m_pluginRoutes[i];
					if (r.method != method) continue;
					if (!matchPluginPath(r.path, qpath, params)) continue;
					receiver  = r.receiver;
					slotBytes = r.slotName.toLatin1();
					found     = true;
					break;
				}
			}

			if (!found) {
				res.status = 404;
				res.set_content(ErrorResponse::build(ErrorCode::ROUTE_NOT_FOUND, req.method + " " + req.path),
				                "application/json");
				return;
			}

			// Plugin routes get the same checks as built-in ones: GET uses the
			// read chain (IP whitelist + auth), every other method the write
			// chain (IP whitelist + rate limit + body size + auth). Runs after
			// matching so unknown paths still return 404 rather than 401.
			{
				auto ctx = toContext(req);
				const MiddlewareChain& chain =
					(method == "GET") ? *m_pReadChain : *m_pWriteChain;
				if (!chain.run(ctx)) {
					applyContext(ctx, res);
					return;
				}
			}

			if (!receiver) {
				res.status = 503;
				res.set_content(ErrorResponse::build(ErrorCode::SERVER_UNAVAILABLE, "plugin handler unloaded"),
				                "application/json");
				return;
			}

			// Wrap path params + body into a single JSON envelope so the slot can
			// access both without a separate signature.
			// All string operations use QByteArray (Qt CRT) to avoid a heap mismatch
			// between Qt's msvcr100 and DazScriptServer's ucrtbase.
			QByteArray body;
			if (!params.isEmpty()) {
				QByteArray paramsJson = "{";
				bool first = true;
				for (auto it = params.begin(); it != params.end(); ++it) {
					if (!first) paramsJson += ",";
					first = false;
					paramsJson += "\"" + it.key().toUtf8() + "\":\"" + it.value().toUtf8() + "\"";
				}
				paramsJson += "}";
				QByteArray rawBody(req.body.c_str(), (int)req.body.size());
				body = "{\"_pathParams\":" + paramsJson + ",\"_body\":" +
				       (rawBody.isEmpty() ? QByteArray("null") : rawBody) + "}";
			} else {
				body = QByteArray(req.body.c_str(), (int)req.body.size());
			}

			QByteArray ip(req.remote_addr.c_str(), (int)req.remote_addr.size());
			HttpResult result;
			QMetaObject::invokeMethod(receiver.data(), slotBytes.constData(),
			                          Qt::BlockingQueuedConnection,
			                          Q_RETURN_ARG(HttpResult, result),
			                          Q_ARG(QByteArray, body),
			                          Q_ARG(QByteArray, ip));
			res.status = result.first;
			if (!result.second.isEmpty())
				res.set_content(result.second.constData(), static_cast<size_t>(result.second.size()),
				                "application/json");
		};
	};

	// The catch-alls must be registered AFTER all specific routes so httplib
	// matches specific paths first (httplib tries handlers in registration order).
	m_pServer->Get   ("/(.*)", makeHandler("GET"));
	m_pServer->Post  ("/(.*)", makeHandler("POST"));
	m_pServer->Put   ("/(.*)", makeHandler("PUT"));
	m_pServer->Delete("/(.*)", makeHandler("DELETE"));
	m_pServer->Patch ("/(.*)", makeHandler("PATCH"));
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
		return {404, ErrorResponse::build(ErrorCode::SCRIPT_NOT_FOUND, id)};
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
		std::string msg = "[WARN] Async queue rejected: " + JsonStd::qstrToStd(r.error);
		QMetaObject::invokeMethod(this, "appendLogBytes", Qt::QueuedConnection,
		    Q_ARG(QByteArray, QByteArray(msg.c_str(), (int)msg.size())));
	}
	return r.id;
}

std::pair<int, std::string> DzScriptServerPane::getAsyncStatusJson(const std::string& requestId)
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

std::pair<int, std::string> DzScriptServerPane::cancelRenderRequestJson(const std::string& requestId,
                                                                        const std::string& clientIP)
{
	std::pair<int, std::string> result = m_pAsyncMgr->cancelRenderJson(requestId, clientIP);
	if (result.first == 200) {
		std::string logLine = "[" + JsonStd::currentTime() + "] [RENDER CANCEL] " + requestId;
		QMetaObject::invokeMethod(this, "appendLogBytes", Qt::QueuedConnection,
		    Q_ARG(QByteArray, QByteArray(logLine.c_str(), (int)logLine.size())));
	}
	return result;
}

std::string DzScriptServerPane::listAsyncRequestsJson(const std::string& statusFilter)
{
	return m_pAsyncMgr->listJson(statusFilter);
}

// ─── Main-thread request handler ──────────────────────────────────────────────

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

	// Capture dzApp debug output (print() in DazScript)
	m_aCapturedLogLines.clear();
	m_bCapturingLog = true;
	connect(dzApp, DSS_DEBUG_SIGNAL,
	        this,  SLOT(onMessagePosted(const QString&)),
	        Qt::DirectConnection);

	// Reuse the persistent DzScript instance instead of constructing/
	// destroying one per request — see m_pPersistentScript's declaration.
	ensurePersistentScript()->clear();

	if (!scriptFile.isEmpty()) {
		// loadFromFile sets the filename so getScriptFileName() and relative
		// include() calls work correctly inside the script.
		if (!m_pPersistentScript->loadFromFile(scriptFile)) {
			disconnect(dzApp, DSS_DEBUG_SIGNAL,
			           this,  SLOT(onMessagePosted(const QString&)));
			m_bCapturingLog = false;
			m_metrics.recordRequest(false);
			return HttpResult(400,
				stdToQBA(ErrorResponse::build(
					ErrorCode::SCRIPT_FILE_LOAD_FAILED, JsonStd::qstrToStd(scriptFile))));
		}
	} else {
		m_pPersistentScript->setCode(scriptText);
	}

	// Args are accessible in scripts via getArguments()[0], since
	// DzScriptContext methods are available as globals in every DzScript.
	ScriptRunResult runResult = runDazScript(m_pPersistentScript, argsMap, scriptFile);
	m_sceneRevision.fetchAndAddOrdered(1);  // the script may have changed anything
#if DAZ_SDK_MAJOR_VERSION >= 6
	m_aCapturedLogLines = runResult.output;  // SDK6: evaluate() bypasses the debugMsg signal
#endif

	QVariant scriptResult = runResult.result;
	QVariant errorVar;
	bool     success = runResult.success;

	if (!success) {
		QString errMsg = runResult.errorMessage;
		if (runResult.errorLine > 0)
			errMsg = QString("Line %1: %2").arg(runResult.errorLine).arg(errMsg);
		errorVar = QVariant(errMsg);
	}

	disconnect(dzApp, DSS_DEBUG_SIGNAL,
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
		QVariantMap parsedBody;
		std::string parseErrDetail;
		if (JsonStd::parseObject(requestBody, parsedBody, parseErrDetail))
			argsMap = parsedBody.value("args").toMap();
	}

	// Execute
	m_aCapturedLogLines.clear();
	m_bCapturingLog = true;
	connect(dzApp, DSS_DEBUG_SIGNAL,
	        this,  SLOT(onMessagePosted(const QString&)),
	        Qt::DirectConnection);

	ensurePersistentScript()->clear();
	m_pPersistentScript->setCode(QString::fromUtf8(scriptText.constData(), scriptText.size()));

	ScriptRunResult runResult = runDazScript(m_pPersistentScript, argsMap, QString());
	m_sceneRevision.fetchAndAddOrdered(1);  // the script may have changed anything
#if DAZ_SDK_MAJOR_VERSION >= 6
	m_aCapturedLogLines = runResult.output;  // SDK6: evaluate() bypasses the debugMsg signal
#endif

	QVariant scriptResult = runResult.result;
	QVariant errorVar;
	bool     success = runResult.success;

	if (!success) {
		QString errMsg = runResult.errorMessage;
		if (runResult.errorLine > 0)
			errMsg = QString("Line %1: %2").arg(runResult.errorLine).arg(errMsg);
		errorVar = QVariant(errMsg);
	}

	disconnect(dzApp, DSS_DEBUG_SIGNAL,
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
		std::string logLine = "[" + JsonStd::currentTime() + "] [" +
			std::string(clientIP.constData(), clientIP.size()) + "] [WARN] [" +
			JsonStd::qstrToStd(requestId) +
			"] Both scriptFile and script provided; using scriptFile";
		QMetaObject::invokeMethod(this, "appendLogBytes", Qt::QueuedConnection,
			Q_ARG(QByteArray, QByteArray(logLine.c_str(), (int)logLine.size())));
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

	std::string logLine = "[" + JsonStd::currentTime() +
		"] [ASYNC QUEUED] script:" + JsonStd::qstrToStd(scriptId) +
		" -> " + JsonStd::qstrToStd(requestId);
	QMetaObject::invokeMethod(this, "appendLogBytes", Qt::QueuedConnection,
		Q_ARG(QByteArray, QByteArray(logLine.c_str(), (int)logLine.size())));

	return buildQueuedResponse(requestId, submittedAt);
}

// ─── Render script generation ─────────────────────────────────────────────────

namespace {

struct FigureSpec {
    QString     name;
    QVariantMap morphs;
};

// DS6 DazScript: mgr["renderFinished(bool)"] is undefined, so a chained
// .connect() throws "Cannot call method 'connect' of undefined" before
// doRender() runs. Look up the signal, then connect only if present.
static QString bindRenderFinishedJs(const char* mgrVar)
{
    return QString(
        "  var _finishedSig = null;\n"
        "  try { _finishedSig = %1[\"renderFinished(bool)\"]; } catch (_eSig) { _finishedSig = null; }\n"
        "  if (!(_finishedSig && typeof _finishedSig.connect === \"function\")) {\n"
        "    try { _finishedSig = %1.renderFinished; } catch (_eSig2) { _finishedSig = null; }\n"
        "  }\n"
        "  var _finishedBound = _finishedSig && typeof _finishedSig.connect === \"function\";\n"
        "  if (_finishedBound) _finishedSig.connect(_onRenderFinished);\n"
    ).arg(QLatin1String(mgrVar));
}

static const char* unbindRenderFinishedJs =
    "    if (_finishedBound && _finishedSig && typeof _finishedSig.disconnect === \"function\")\n"
    "      _finishedSig.disconnect(_onRenderFinished);\n";

// Reads an optional "iray_samples" field from a request object. Absent → keeps
// *out (the caller's default); 0 means "use the scene's Iray setting". Rejects
// non-integers and negatives so a typo can't silently become "scene default".
// The upper bound is the live property's clamp, checked in the render script.
static bool readIraySamples(const QVariantMap& m, int* out, std::string* err)
{
    if (!m.contains("iray_samples")) return true;
    const QVariant v = m.value("iray_samples");
    bool numeric = false;
    switch (v.type()) {
    case QVariant::Int: case QVariant::LongLong:
    case QVariant::UInt: case QVariant::ULongLong: case QVariant::Double:
        numeric = true; break;
    default: break;
    }
    const double d = numeric ? v.toDouble() : -1.0;
    if (!numeric || d != (double)(long long)d || d < 0 || d > 2147483647.0) {
        *err = "iray_samples must be a non-negative integer (0 = scene default)";
        return false;
    }
    *out = (int)d;
    return true;
}

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
    //   MainWindow.getViewportMgr().getActiveViewport().get3DViewport().setCamera()
    //     is the verified viewport-camera setter (see dazpy/_viewport.py,
    //     vangard_daz_mcp/_registry.py's _SET_ACTIVE_CAMERA_SCRIPT). Neither
    //     App.getViewportMgr() nor DzViewportMgr.setActiveCamera() exist on this
    //     DAZ Studio version — both throw TypeError; don't reintroduce them.
    //   opts.camera  is the property doRender() actually reads to pick the render
    //     camera — setting only the viewport's active camera leaves this stale/null
    //     and produces a black render. Must set both (see dazpy/_render.py, and
    //     vangard_daz_mcp/_registry.py's camera-preset/render scripts).
    //   renderMgr.doRender(opts)  confirmed in dzrendermgr.h
    //   Engine switching: "viewport" sets opts.renderType = ScreenShot; "iray"/
    //     "filament" look the renderer up by class name via
    //     renderMgr.findRenderer() (runtime-registered, so not in the SDK
    //     headers), activate it with setActiveRenderer(), set renderType =
    //     Software, then read both back and throw on any mismatch (below).
    //   iray_samples: not a DzRenderOptions property — applied below through
    //     the Iray renderer's property holder ("Max Samples").
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
        "    if (cam) {\n"
        "      opts.camera = cam;\n"
        "      var viewportMgr = MainWindow.getViewportMgr();\n"
        "      var activeViewport = viewportMgr ? viewportMgr.getActiveViewport() : null;\n"
        "      if (activeViewport) activeViewport.get3DViewport().setCamera(cam);\n"
        "    }\n"
        "  }\n";

    // renderType is the effective operation selector. Active renderer identity
    // is read separately because DAZ retains it during Viewport/OpenGL renders.
    script +=
        "  var engineReadback = null;\n"
        "  if (engineName) {\n"
        "    var requestedEngine = engineName.toLowerCase();\n"
        "    var engineMap = {\"iray\": \"DzIrayRenderer\", \"filament\": \"DzFilamentRenderer\"};\n"
        "    var requestedClass = engineMap[requestedEngine];\n"
        "    if (requestedEngine === \"viewport\") {\n"
        "      opts.renderType = opts.ScreenShot;\n"
        "    } else {\n"
        "      if (!requestedClass) throw new Error(\"Unknown render engine request: \" + requestedEngine);\n"
        "      var requestedRenderer = renderMgr.findRenderer(requestedClass);\n"
        "      if (!requestedRenderer) throw new Error(\"Render engine is not registered: \" + requestedClass);\n"
        "      renderMgr.setActiveRenderer(requestedRenderer);\n"
        "      opts.renderType = opts.Software;\n"
        "    }\n"
        "    opts.applyChanges();\n"
        "    var effectiveType = Number(opts.renderType);\n"
        "    var effectiveRenderer = renderMgr.getActiveRenderer();\n"
        "    var effectiveClass = effectiveRenderer ? String(effectiveRenderer.className()) : null;\n"
        "    var effectiveName = effectiveRenderer ? String(effectiveRenderer.getName()) : null;\n"
        "    var exactMatch = requestedEngine === \"viewport\"\n"
        "      ? effectiveType === Number(opts.ScreenShot)\n"
        "      : effectiveType === Number(opts.Software) && effectiveClass === requestedClass;\n"
        "    if (!exactMatch) throw new Error(\"Render engine readback mismatch for request: \" + requestedEngine);\n"
        "    var typeName = effectiveType === Number(opts.ScreenShot) ? \"ScreenShot\"\n"
        "      : effectiveType === Number(opts.HardwareAssisted) ? \"HardwareAssisted\"\n"
        "      : effectiveType === Number(opts.Software) ? \"Software\" : null;\n"
        "    engineReadback = {\n"
        "      selector_schema: 1,\n"
        "      status: requestedEngine === \"iray\" ? \"verified_iray\" : \"verified_non_iray\",\n"
        "      engine: requestedEngine === \"iray\" ? \"iray\" : (requestedEngine === \"viewport\" ? \"viewport_gl\" : \"other_non_iray\"),\n"
        "      method: \"render_settings_engine_selector\",\n"
        "      reason: requestedEngine === \"iray\" ? null : \"non_iray_engine\",\n"
        "      render_type: {raw: effectiveType, name: typeName, provenance: {kind: \"live_readback\", source: \"DzRenderOptions.renderType\"}},\n"
        "      active_renderer: {class_name: effectiveClass, name: effectiveName, provenance: {kind: \"live_readback\", source: \"DzRenderMgr.getActiveRenderer\"}}\n"
        "    };\n"
        "  }\n";

    // iray_samples: Iray's sample cap is the "Max Samples" DzIntProperty on
    // renderMgr.getActiveRenderer().getPropertyHolder() (confirmed live on
    // DS 6.26: clamped -1..25000; same path dazpy/_render.py uses for
    // max_samples). It's a per-render override: the previous value is
    // restored after doRender() so the request doesn't leak into the user's
    // persistent render settings. The request fails (rather than silently
    // rendering with the scene default) if the effective render isn't an
    // Iray software render, the property can't be found, the value is out
    // of the property's range, or the readback doesn't match.
    script +=
        "  var irayReadback = null;\n"
        "  var _maxSamplesProp = null;\n"
        "  var _prevMaxSamples = null;\n"
        "  if (iraySamples > 0) {\n"
        "    var _iRenderer = renderMgr.getActiveRenderer();\n"
        "    var _iClass = _iRenderer ? String(_iRenderer.className()) : null;\n"
        "    if (_iClass !== \"DzIrayRenderer\" || Number(opts.renderType) !== Number(opts.Software))\n"
        "      throw new Error(\"iray_samples requires an Iray render; effective renderer is \" + _iClass"
        " + \" with renderType \" + Number(opts.renderType));\n"
        "    var _iHolder = _iRenderer.getPropertyHolder();\n"
        "    var _iProp = _iHolder ? _iHolder.findProperty(\"Max Samples\") : null;\n"
        "    if (!_iProp) throw new Error(\"iray_samples: Iray 'Max Samples' property not found\");\n"
        "    if (_iProp.isClamped && _iProp.isClamped()\n"
        "        && (iraySamples < _iProp.getMin() || iraySamples > _iProp.getMax()))\n"
        "      throw new Error(\"iray_samples \" + iraySamples + \" is outside the supported range \"\n"
        "        + _iProp.getMin() + \"..\" + _iProp.getMax());\n"
        "    _prevMaxSamples = Number(_iProp.getValue());\n"
        "    _maxSamplesProp = _iProp;\n"
        "    _iProp.setValue(iraySamples);\n"
        "    var _applied = Number(_iProp.getValue());\n"
        "    if (_applied !== iraySamples) {\n"
        "      _iProp.setValue(_prevMaxSamples);\n"
        "      throw new Error(\"iray_samples readback mismatch: requested \" + iraySamples + \", got \" + _applied);\n"
        "    }\n"
        "    irayReadback = {\n"
        "      requested: iraySamples, applied: _applied, previous: _prevMaxSamples, restored: false,\n"
        "      provenance: {kind: \"live_readback\", source: \"DzIrayRenderer.getPropertyHolder().findProperty('Max Samples')\"}\n"
        "    };\n"
        "  }\n\n";

    // ── Render ────────────────────────────────────────────────────────────
    // doRender()'s own return value is undocumented in the SDK (no
    // "Returns:" section at all) and was observed live to report success
    // even for a render the user cancelled mid-progress via the DAZ Studio
    // UI. renderFinished(bool succeeded) is the SDK's explicit, named
    // completion signal -- SceneEventBroker.cpp already relies on it as the
    // "guaranteed exit path" that fires correctly across error/cancel cases
    // -- so capture it directly instead of hardcoding success.
    script +=
        "  var renderSucceeded = null;\n"
        "  function _onRenderFinished(succeeded) { renderSucceeded = succeeded; }\n";
    script += bindRenderFinishedJs("renderMgr");
    script +=
        "  try {\n"
        "    renderMgr.doRender(opts);\n"
        "    if (!_finishedBound && renderSucceeded === null) renderSucceeded = true;\n"
        "  } finally {\n";
    script += unbindRenderFinishedJs;
    script +=
        "    if (_maxSamplesProp) {\n"
        "      _maxSamplesProp.setValue(_prevMaxSamples);\n"
        "      irayReadback.restored = Number(_maxSamplesProp.getValue()) === _prevMaxSamples;\n"
        "    }\n"
        "  }\n"
        "  return {success: renderSucceeded === true, output_path: outputPath, engine: engineReadback,"
        " iray_samples: irayReadback};\n"
        "})();\n";

    return script;
}

// Builds the DazScript that loops a frame range, moving the scene's playhead
// with Scene.setFrame() (confirmed in dzscene.h) and rendering one file per
// frame. outputPattern must contain the literal token "{frame}", which is
// replaced with the frame number zero-padded to framePadding digits.
//
// Restores the original current frame after the loop so the render doesn't
// leave the scene's timeline position mutated.
static QString buildAnimationRenderScript(
    const QString& outputPattern,
    int startFrame, int endFrame, int framePadding,
    int width, int height,
    const QString& camera,
    const QString& engine,
    const QString& frameReportFile)
{
    QString outputPatternEsc = QString::fromStdString(
        JsonStd::escape(JsonStd::qstrToStd(outputPattern)));
    QString frameReportEsc = frameReportFile.isEmpty() ? QString("null")
        : "\"" + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(frameReportFile))) + "\"";
    QString cameraEsc = camera.isEmpty() ? QString("null")
        : "\"" + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(camera))) + "\"";
    QString engineEsc = engine.isEmpty() ? QString("null")
        : "\"" + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(engine))) + "\"";

    QString script;
    script += "(function() {\n";
    script += "  var outputPattern = \"" + outputPatternEsc + "\";\n";
    script += "  var startFrame = " + QString::number(startFrame) + ";\n";
    script += "  var endFrame = " + QString::number(endFrame) + ";\n";
    script += "  var framePadding = " + QString::number(framePadding) + ";\n";
    script += "  var cameraName = " + cameraEsc + ";\n";
    script += "  var engineName = " + engineEsc + ";\n";
    script += "  var width = " + QString::number(width) + ";\n";
    script += "  var height = " + QString::number(height) + ";\n";
    script += "  var frameReportFile = " + frameReportEsc + ";\n\n";

    script +=
        "  function padFrame(n, width) {\n"
        "    var s = String(n);\n"
        "    while (s.length < width) s = \"0\" + s;\n"
        "    return s;\n"
        "  }\n\n";

    // ── Frame progress report ─────────────────────────────────────────────
    // On Studio 6 print() is shimmed into an array (see runDazScript), so the
    // [DAZPY_FRAME] marker below never reaches onMessagePosted while the job
    // runs. The server-owned JSONL report is read live by polling workers
    // instead. The whole event list is rewritten each frame (the same
    // pattern the report-file tests use) rather than relying on an append
    // open mode. Best effort: a failed write must never fail the render.
    script +=
        "  var frameEvents = \"\";\n"
        "  function reportFrame(frame, total) {\n"
        "    if (!frameReportFile) return;\n"
        "    try {\n"
        "      frameEvents += JSON.stringify({type: \"progress\", value: (frame - 1) / total,\n"
        "        current: frame - 1, total: total, frame: frame, phase: \"rendering\",\n"
        "        message: \"Rendering frame \" + frame + \" of \" + total}) + \"\\n\";\n"
        "      var rf = new DzFile(frameReportFile);\n"
        "      if (rf.open(DzFile.WriteOnly)) { rf.write(frameEvents); rf.close(); }\n"
        "    } catch (e) {}\n"
        "  }\n\n";

    // ── Configure render options (shared across all frames) ───────────────
    script +=
        "  var renderMgr = App.getRenderMgr();\n"
        "  var opts = renderMgr.getRenderOptions();\n"
        "  opts.renderImgToId = 2;\n";  // DirectToFile
    script +=
        "  if (width > 0) opts.imageSize = new QSize(width, height);\n";
    script +=
        "  if (cameraName) {\n"
        "    var cam = Scene.findCameraByLabel(cameraName);\n"
        "    if (!cam) return {success: false, error: 'Camera not found: ' + cameraName};\n"
        "    opts.camera = cam;\n"
        "    var viewportMgr = MainWindow.getViewportMgr();\n"
        "    var activeViewport = viewportMgr ? viewportMgr.getActiveViewport() : null;\n"
        "    if (activeViewport) activeViewport.get3DViewport().setCamera(cam);\n"
        "  }\n";
    script +=
        "  var engineReadback = null;\n"
        "  if (engineName) {\n"
        "    var requestedEngine = engineName.toLowerCase();\n"
        "    var engineMap = {\"iray\": \"DzIrayRenderer\", \"filament\": \"DzFilamentRenderer\"};\n"
        "    var requestedClass = engineMap[requestedEngine];\n"
        "    if (requestedEngine === \"viewport\") {\n"
        "      opts.renderType = opts.ScreenShot;\n"
        "    } else {\n"
        "      if (!requestedClass) throw new Error(\"Unknown render engine request: \" + requestedEngine);\n"
        "      var requestedRenderer = renderMgr.findRenderer(requestedClass);\n"
        "      if (!requestedRenderer) throw new Error(\"Render engine is not registered: \" + requestedClass);\n"
        "      renderMgr.setActiveRenderer(requestedRenderer);\n"
        "      opts.renderType = opts.Software;\n"
        "    }\n"
        "    opts.applyChanges();\n"
        "    var effectiveType = Number(opts.renderType);\n"
        "    var effectiveRenderer = renderMgr.getActiveRenderer();\n"
        "    var effectiveClass = effectiveRenderer ? String(effectiveRenderer.className()) : null;\n"
        "    var effectiveName = effectiveRenderer ? String(effectiveRenderer.getName()) : null;\n"
        "    var exactMatch = requestedEngine === \"viewport\"\n"
        "      ? effectiveType === Number(opts.ScreenShot)\n"
        "      : effectiveType === Number(opts.Software) && effectiveClass === requestedClass;\n"
        "    if (!exactMatch) throw new Error(\"Render engine readback mismatch for request: \" + requestedEngine);\n"
        "    var typeName = effectiveType === Number(opts.ScreenShot) ? \"ScreenShot\"\n"
        "      : effectiveType === Number(opts.HardwareAssisted) ? \"HardwareAssisted\"\n"
        "      : effectiveType === Number(opts.Software) ? \"Software\" : null;\n"
        "    engineReadback = {\n"
        "      selector_schema: 1,\n"
        "      status: requestedEngine === \"iray\" ? \"verified_iray\" : \"verified_non_iray\",\n"
        "      engine: requestedEngine === \"iray\" ? \"iray\" : (requestedEngine === \"viewport\" ? \"viewport_gl\" : \"other_non_iray\"),\n"
        "      method: \"render_settings_engine_selector\",\n"
        "      reason: requestedEngine === \"iray\" ? null : \"non_iray_engine\",\n"
        "      render_type: {raw: effectiveType, name: typeName, provenance: {kind: \"live_readback\", source: \"DzRenderOptions.renderType\"}},\n"
        "      active_renderer: {class_name: effectiveClass, name: effectiveName, provenance: {kind: \"live_readback\", source: \"DzRenderMgr.getActiveRenderer\"}}\n"
        "    };\n"
        "  }\n\n";

    // ── Render each frame ───────────────────────────────────────────────────
    // doRender()'s own return value is undocumented in the SDK (no
    // "Returns:" section at all) and was observed live to report success
    // even for a render the user cancelled mid-progress via the DAZ Studio
    // UI. renderFinished(bool succeeded) is the SDK's explicit, named
    // completion signal -- SceneEventBroker.cpp already relies on it as the
    // "guaranteed exit path" that fires correctly across error/cancel cases
    // -- so capture it per frame instead of hardcoding success.
    script +=
        "  var originalFrame = Scene.getFrame();\n"
        "  var outputPaths = [];\n"
        "  var allSucceeded = true;\n"
        "  var frameSucceeded = null;\n"
        "  function _onRenderFinished(succeeded) { frameSucceeded = succeeded; }\n";
    script += bindRenderFinishedJs("renderMgr");
    script +=
        "  try {\n"
        "    for (var f = startFrame; f <= endFrame; f++) {\n"
        "      Scene.setFrame(f);\n"
        "      var framePath = outputPattern.replace('{frame}', padFrame(f, framePadding));\n"
        "      opts.renderImgFilename = framePath;\n"
        "      frameSucceeded = null;\n"
        "      reportFrame(f - startFrame + 1, endFrame - startFrame + 1);\n"
        "      print(\"[DAZPY_FRAME] \" + (f - startFrame + 1) + \"/\" + (endFrame - startFrame + 1));\n"
        "      renderMgr.doRender(opts);\n"
        "      if (_finishedBound && frameSucceeded !== true) allSucceeded = false;\n"
        "      outputPaths.push(framePath);\n"
        "    }\n"
        "  } finally {\n";
    script += unbindRenderFinishedJs;
    script +=
        "  }\n"
        "  Scene.setFrame(originalFrame);\n\n";

    script +=
        "  return {success: allSucceeded, frame_count: outputPaths.length, output_paths: outputPaths, engine: engineReadback};\n"
        "})();\n";

    return script;
}

} // namespace

// ─────────────────────────────────────────────────────────────────────────────

HttpResult DzScriptServerPane::handleAsyncRenderEnqueue(const QByteArray& jsonBody,
                                               const QByteArray& correlationId)
{
    const QString corr = QString::fromUtf8(correlationId.constData(), correlationId.size());
    // ── Parse body ────────────────────────────────────────────────────────
    QVariantMap body;
    std::string parseErrDetail;
    if (!JsonStd::parseObject(jsonBody, body, parseErrDetail))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));

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
    int  iraySamples = 0;
    bool resetMorphs = body.value("reset_morphs").toBool();
    QString camera   = body.value("camera").toString().trimmed();
    QString engine   = body.value("engine").toString().trimmed().toLower();

    {
        std::string err;
        if (!readIraySamples(body, &iraySamples, &err))
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD, err)));
    }
    if (iraySamples > 0 && (engine == "viewport" || engine == "filament"))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "iray_samples requires the iray engine")));

    if ((width > 0) != (height > 0))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "width and height must both be provided or both omitted")));

    if (width < 0 || height < 0)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "width and height must be positive integers")));

    if (!engine.isEmpty()
            && engine != "iray" && engine != "viewport" && engine != "filament")
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "engine must be one of: iray, viewport, filament")));

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

        ensurePersistentScript()->clear();
        m_pPersistentScript->setCode(validateScript);
        ScriptRunResult valRunResult = runDazScript(m_pPersistentScript, QVariantMap(), QString());
        if (valRunResult.success) {
            QString valResult = valRunResult.result.toString();
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

    AsyncRequestManager::SubmitResult sr = m_pAsyncMgr->submitRender(renderScript, "rnd", corr);
    if (!sr.accepted)
        return HttpResult(503, stdToQBA(ErrorResponse::build(
            ErrorCode::SERVER_UNAVAILABLE, JsonStd::qstrToStd(sr.error))));

    m_pRenderProgress->setOutputPath(sr.id, outputPath);

    appendLog(QString("[%1] [RENDER QUEUED] output:%2 -> %3")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
        .arg(outputPath).arg(sr.id));

    return buildQueuedResponse(sr.id, sr.submittedAt);
}

HttpResult DzScriptServerPane::handleAsyncRenderBatchEnqueue(const QByteArray& jsonBody,
                                               const QByteArray& correlationId)
{
    const QString corr = QString::fromUtf8(correlationId.constData(), correlationId.size());
    // ── Parse body ────────────────────────────────────────────────────────
    QVariantMap body;
    std::string parseErrDetail;
    if (!JsonStd::parseObject(jsonBody, body, parseErrDetail))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));

    // ── Parse base (all fields optional — provides defaults for variants) ─
    QVariantMap base = body.value("base").toMap();

    int     baseWidth       = base.contains("width")        ? base.value("width").toInt()        : 0;
    int     baseHeight      = base.contains("height")       ? base.value("height").toInt()       : 0;
    int     baseIraySamples = 0;
    {
        std::string err;
        if (!readIraySamples(base, &baseIraySamples, &err))
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD, "base." + err)));
    }
    bool    baseResetMorphs = base.value("reset_morphs").toBool();
    QString baseCamera      = base.value("camera").toString().trimmed();
    QString baseEngine      = base.value("engine").toString().trimmed().toLower();

    // Resolve base figures (single-figure shorthand or explicit list)
    QList<FigureSpec> baseFigures;
    if (base.contains("figures")) {
        QVariantList figs = base.value("figures").toList();
        for (int i = 0; i < figs.size(); ++i) {
            QVariantMap fig = figs[i].toMap();
            QString name = fig.value("name").toString().trimmed();
            if (name.isEmpty())
                return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD,
                    "base.figures[" + std::to_string(i) + "].name")));
            FigureSpec spec;
            spec.name   = name;
            spec.morphs = fig.value("morphs").toMap();
            baseFigures.append(spec);
        }
    } else if (base.contains("figure")) {
        QString name = base.value("figure").toString().trimmed();
        if (!name.isEmpty()) {
            FigureSpec spec;
            spec.name   = name;
            spec.morphs = base.value("morphs").toMap();
            baseFigures.append(spec);
        }
    }

    // ── Validate variants array ───────────────────────────────────────────
    if (!body.contains("variants"))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD, "variants")));

    QVariantList variants = body.value("variants").toList();
    if (variants.isEmpty())
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "variants must be a non-empty array")));

    const int MAX_BATCH_VARIANTS = ServerConfig::MAX_BATCH_VARIANTS;
    if (variants.size() > MAX_BATCH_VARIANTS)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "variants exceeds maximum of " + std::to_string(MAX_BATCH_VARIANTS))));

    // ── Validate + pre-flight all variants before enqueuing any ──────────
    struct VariantSpec {
        QString           outputPath;
        int               width, height, iraySamples;
        bool              resetMorphs;
        QString           camera, engine;
        QList<FigureSpec> figures;
        QString           renderScript;
    };
    QList<VariantSpec> specs;
    specs.reserve(variants.size());

    for (int vi = 0; vi < variants.size(); ++vi) {
        QVariantMap v = variants[vi].toMap();
        const std::string viStr = "variants[" + std::to_string(vi) + "]";

        // output_path required per variant
        QString outputPath = v.value("output_path").toString().trimmed();
        {
            ValidationResult vr = RequestValidator::validateRequiredField(outputPath,
                viStr + ".output_path");
            if (!vr.valid)
                return HttpResult(vr.httpStatus(), stdToQBA(vr.toErrorJson()));
        }

        // Merge scalar fields: variant overrides base
        int     width       = v.contains("width")        ? v.value("width").toInt()        : baseWidth;
        int     height      = v.contains("height")       ? v.value("height").toInt()       : baseHeight;
        int     iraySamples = baseIraySamples;
        {
            std::string err;
            if (!readIraySamples(v, &iraySamples, &err))
                return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                    viStr + "." + err)));
        }
        bool    resetMorphs = v.contains("reset_morphs") ? v.value("reset_morphs").toBool(): baseResetMorphs;
        QString camera      = v.contains("camera")       ? v.value("camera").toString().trimmed() : baseCamera;
        QString engine      = v.contains("engine")       ? v.value("engine").toString().trimmed().toLower() : baseEngine;

        if ((width > 0) != (height > 0))
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                viStr + ": width and height must both be provided or both omitted")));
        if (width < 0 || height < 0)
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                viStr + ": width and height must be positive integers")));
        if (!engine.isEmpty()
                && engine != "iray" && engine != "viewport" && engine != "filament")
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                viStr + ".engine must be one of: iray, viewport, filament")));
        if (iraySamples > 0 && (engine == "viewport" || engine == "filament"))
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                viStr + ": iray_samples requires the iray engine")));

        // Merge figures: variant wins if it specifies figures/figure;
        // if variant only has morphs and base has one figure, override its morphs.
        QList<FigureSpec> figures;
        if (v.contains("figures")) {
            QVariantList figs = v.value("figures").toList();
            for (int i = 0; i < figs.size(); ++i) {
                QVariantMap fig = figs[i].toMap();
                QString name = fig.value("name").toString().trimmed();
                if (name.isEmpty())
                    return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD,
                        viStr + ".figures[" + std::to_string(i) + "].name")));
                FigureSpec spec;
                spec.name   = name;
                spec.morphs = fig.value("morphs").toMap();
                figures.append(spec);
            }
        } else if (v.contains("figure")) {
            FigureSpec spec;
            spec.name   = v.value("figure").toString().trimmed();
            spec.morphs = v.value("morphs").toMap();
            figures.append(spec);
        } else if (v.contains("morphs") && baseFigures.size() == 1) {
            // Shorthand: apply morph overrides on top of the single base figure's morphs
            QVariantMap merged = baseFigures[0].morphs;
            QVariantMap overrides = v.value("morphs").toMap();
            for (QVariantMap::const_iterator it = overrides.begin(); it != overrides.end(); ++it)
                merged[it.key()] = it.value();
            FigureSpec spec;
            spec.name   = baseFigures[0].name;
            spec.morphs = merged;
            figures.append(spec);
        } else {
            figures = baseFigures;
        }

        // Pre-flight: validate figure names against the current scene
        if (!figures.isEmpty()) {
            QString validateScript = "(function() {\n  var names = [";
            for (int i = 0; i < figures.size(); ++i) {
                if (i > 0) validateScript += ",";
                validateScript += "\"";
                validateScript += QString::fromStdString(
                    JsonStd::escape(JsonStd::qstrToStd(figures[i].name)));
                validateScript += "\"";
            }
            validateScript +=
                "];\n"
                "  for (var i = 0; i < names.length; i++) {\n"
                "    if (!Scene.findNodeByLabel(names[i])) return 'NOT_FOUND:' + names[i];\n"
                "  }\n"
                "  return 'OK';\n"
                "})()";
            ensurePersistentScript()->clear();
            m_pPersistentScript->setCode(validateScript);
            ScriptRunResult valRunResult = runDazScript(m_pPersistentScript, QVariantMap(), QString());
            if (valRunResult.success) {
                QString valResult = valRunResult.result.toString();
                if (valResult.startsWith("NOT_FOUND:")) {
                    QString missing = valResult.mid(10);
                    return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                        viStr + ": Figure not found in scene: " + JsonStd::qstrToStd(missing))));
                }
            }
        }

        VariantSpec vs;
        vs.outputPath   = outputPath;
        vs.width        = width;
        vs.height       = height;
        vs.iraySamples  = iraySamples;
        vs.resetMorphs  = resetMorphs;
        vs.camera       = camera;
        vs.engine       = engine;
        vs.figures      = figures;
        vs.renderScript = buildRenderScript(
            outputPath, width, height, camera, engine, iraySamples, resetMorphs, figures);
        specs.append(vs);
    }

    // ── Enqueue all variants ──────────────────────────────────────────────
    QString batchId = MetricsCollector::generateAsyncId("bat");
    QStringList requestIds;

    for (int vi = 0; vi < specs.size(); ++vi) {
        AsyncRequestManager::SubmitResult sr =
            m_pAsyncMgr->submitRender(specs[vi].renderScript, "rnd", corr);
        if (!sr.accepted) {
            // Queue full mid-batch — return 503 with how many were accepted.
            // Already-enqueued variants will still execute.
            std::string msg = "Queue full after accepting " + std::to_string(requestIds.size())
                + " of " + std::to_string(specs.size()) + " variants: " + JsonStd::qstrToStd(sr.error);
            return HttpResult(503, stdToQBA(ErrorResponse::build(ErrorCode::SERVER_UNAVAILABLE, msg)));
        }
        m_pRenderProgress->setOutputPath(sr.id, specs[vi].outputPath);
        requestIds.append(sr.id);
    }

    // ── Build response ────────────────────────────────────────────────────
    std::string resp = "{\"batch_id\":\"" + JsonStd::qstrToStd(batchId) + "\""
        + ",\"request_ids\":[";
    for (int i = 0; i < requestIds.size(); ++i) {
        if (i > 0) resp += ",";
        resp += "\"" + JsonStd::qstrToStd(requestIds[i]) + "\"";
    }
    resp += "],\"total\":" + std::to_string(requestIds.size()) + "}";

    appendLog(QString("[%1] [BATCH QUEUED] batch:%2 variants:%3")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
        .arg(batchId)
        .arg(requestIds.size()));

    return HttpResult(200, QByteArray(resp.c_str(), (int)resp.size()));
}

HttpResult DzScriptServerPane::handleAsyncRenderAnimationEnqueue(const QByteArray& jsonBody,
                                               const QByteArray& correlationId)
{
    const QString corr = QString::fromUtf8(correlationId.constData(), correlationId.size());
    // ── Parse body ────────────────────────────────────────────────────────
    QVariantMap body;
    std::string parseErrDetail;
    if (!JsonStd::parseObject(jsonBody, body, parseErrDetail))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_JSON)));

    // ── Required fields ───────────────────────────────────────────────────
    QString outputPath = body.value("output_path").toString().trimmed();
    {
        ValidationResult vr = RequestValidator::validateRequiredField(outputPath, "output_path");
        if (!vr.valid)
            return HttpResult(vr.httpStatus(), stdToQBA(vr.toErrorJson()));
    }
    if (!outputPath.contains("{frame}"))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "output_path must contain the literal token {frame}")));

    if (!body.contains("start_frame"))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD, "start_frame")));
    if (!body.contains("end_frame"))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::MISSING_FIELD, "end_frame")));

    int startFrame = body.value("start_frame").toInt();
    int endFrame   = body.value("end_frame").toInt();
    if (startFrame < 0 || endFrame < 0)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "start_frame and end_frame must be non-negative integers")));
    if (endFrame < startFrame)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "end_frame must be >= start_frame")));

    const int MAX_ANIMATION_FRAMES = ServerConfig::MAX_ANIMATION_FRAMES;
    int frameCount = endFrame - startFrame + 1;
    if (frameCount > MAX_ANIMATION_FRAMES)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "frame range exceeds maximum of " + std::to_string(MAX_ANIMATION_FRAMES) + " frames")));

    // ── Optional fields ───────────────────────────────────────────────────
    int framePadding = body.contains("frame_padding") ? body.value("frame_padding").toInt() : 4;
    if (framePadding < 1 || framePadding > 10)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "frame_padding must be between 1 and 10")));

    int  width  = body.contains("width")  ? body.value("width").toInt()  : 0;
    int  height = body.contains("height") ? body.value("height").toInt() : 0;
    QString camera = body.value("camera").toString().trimmed();
    QString engine = body.value("engine").toString().trimmed().toLower();

    if ((width > 0) != (height > 0))
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "width and height must both be provided or both omitted")));
    if (width < 0 || height < 0)
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "width and height must be positive integers")));
    if (!engine.isEmpty()
            && engine != "iray" && engine != "viewport" && engine != "filament")
        return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
            "engine must be one of: iray, viewport, filament")));

    // ── Pre-flight: validate camera reference against the current scene ───
    if (!camera.isEmpty()) {
        QString validateScript = "(function() {\n"
            "  return Scene.findCameraByLabel(\""
            + QString::fromStdString(JsonStd::escape(JsonStd::qstrToStd(camera)))
            + "\") ? 'OK' : 'NOT_FOUND';\n"
            "})()";
        ensurePersistentScript()->clear();
        m_pPersistentScript->setCode(validateScript);
        ScriptRunResult valRunResult = runDazScript(m_pPersistentScript, QVariantMap(), QString());
        if (valRunResult.success && valRunResult.result.toString() == "NOT_FOUND")
            return HttpResult(400, stdToQBA(ErrorResponse::build(ErrorCode::INVALID_FIELD,
                "Camera not found in scene: " + JsonStd::qstrToStd(camera))));
    }

    // ── Generate and enqueue animation render job ─────────────────────────
    // Server-owned per-job frame report (see buildAnimationRenderScript).
    // A random name, not the request ID: the script is built before the job
    // is submitted, and the name must not be guessable or reused.
    QString reportToken = SecureRandom::generateHexToken(8);
    if (reportToken.isEmpty())
        reportToken = QUuid::createUuid().toString().mid(1, 8);
    const QString frameReportFile =
        QDir(QDir::tempPath()).filePath("dss-frames-" + reportToken + ".jsonl");

    QString renderScript = buildAnimationRenderScript(
        outputPath, startFrame, endFrame, framePadding, width, height, camera, engine,
        frameReportFile);

    AsyncRequestManager::SubmitResult sr =
        m_pAsyncMgr->submitRender(renderScript, "rnd", corr, frameReportFile);
    if (!sr.accepted)
        return HttpResult(503, stdToQBA(ErrorResponse::build(
            ErrorCode::SERVER_UNAVAILABLE, JsonStd::qstrToStd(sr.error))));

    m_pRenderProgress->setOutputPath(sr.id, outputPath);

    appendLog(QString("[%1] [ANIMATION RENDER QUEUED] frames:%2-%3 output:%4 -> %5")
        .arg(QDateTime::currentDateTime().toString("HH:mm:ss"))
        .arg(startFrame).arg(endFrame)
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
	m_nStaleJobTimeoutMin    = s.staleJobTimeoutMin;

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
	s.staleJobTimeoutMin    = m_nStaleJobTimeoutMin;
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
		for (const QString& msg : msgs)
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

// Only cleanupExpiredRequests() (main thread) reads the timeout, so it can be
// changed while the server is running without a restart.
void DzScriptServerPane::onStaleTimeoutChanged(int minutes)
{
	m_nStaleJobTimeoutMin = minutes;
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
	s += ",\"server_instance_id\":\"";
	s.append(m_serverInstanceId.constData(), m_serverInstanceId.size());
	s += "\",\"scene_revision\":";
	s += std::to_string(sceneRevision());
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
	s += ",\"avg_main_thread_wait_ms\":";
	s += std::to_string((long long)m_metrics.getAvgMainThreadWaitMs());
	s += ",\"max_main_thread_wait_ms\":";
	s += std::to_string((long long)m_metrics.getMaxMainThreadWaitMs());
	s += "}";
	return s;
}

// ─── Capabilities (GET /capabilities) ─────────────────────────────────────────

namespace {

// Core route table reported by GET /capabilities. Paths use OpenAPI-style
// {id} placeholders for the ([^/]+) captures in setupRoutes().
// tests/test_route_security.py fails if this table and setupRoutes() drift apart.
struct CapabilityRoute {
	const char* method;
	const char* path;
	bool        auth;     // false only for the deliberately public routes
	const char* kind;     // "json" | "sse" | "binary"
};

const CapabilityRoute kCapabilityRoutes[] = {
	{ "GET",    "/status",                 false, "json"   },
	{ "GET",    "/health",                 false, "json"   },
	{ "GET",    "/metrics",                false, "json"   },
	{ "GET",    "/capabilities",           true,  "json"   },
	{ "POST",   "/execute",                true,  "json"   },
	{ "POST",   "/scripts/register",       true,  "json"   },
	{ "GET",    "/scripts",                true,  "json"   },
	{ "DELETE", "/scripts/{id}",           true,  "json"   },
	{ "POST",   "/scripts/{id}/execute",   true,  "json"   },
	{ "POST",   "/execute/async",          true,  "json"   },
	{ "POST",   "/scripts/{id}/async",     true,  "json"   },
	{ "GET",    "/requests/{id}/status",   true,  "json"   },
	{ "GET",    "/requests/{id}/result",   true,  "json"   },
	{ "DELETE", "/requests/{id}",          true,  "json"   },
	{ "GET",    "/requests",               true,  "json"   },
	{ "GET",    "/artifacts/{id}",         true,  "json"   },
	{ "GET",    "/artifacts/{id}/{artifact_id}", true, "binary" },
	{ "POST",   "/render",                 true,  "json"   },
	{ "POST",   "/render/batch",           true,  "json"   },
	{ "POST",   "/render/animation",       true,  "json"   },
	{ "POST",   "/render/{id}/cancel",     true,  "json"   },
	{ "POST",   "/scene/save-copy",        true,  "json"   },
	{ "POST",   "/geometry/frames",        true,  "binary" },
	{ "GET",    "/scene/events",           true,  "sse"    },
	{ "GET",    "/render/{id}/progress",   true,  "sse"    },
};

// Engines POST /render accepts in its "engine" field, and the renderer class
// each one needs (null = no renderer lookup; viewport uses a ScreenShot render).
struct SelectableEngine {
	const char* engine;
	const char* rendererClass;
};

const SelectableEngine kSelectableEngines[] = {
	{ "viewport", nullptr },
	{ "iray",     "DzIrayRenderer" },
	{ "filament", "DzFilamentRenderer" },
};

} // namespace

QByteArray DzScriptServerPane::buildCapabilitiesJson(const QString& engineSource) const
{
	// Main thread only: reads GUI-owned settings and DzRenderMgr.
	//
	// Written straight to JSON on purpose. A QVariantList built here allocates
	// its QVariant* nodes with this DLL's CRT (ucrtbase); stored inside a
	// QVariant/QVariantMap, the last reference is released by QtCore's
	// ~QVariant, which frees them with Qt's CRT (msvcr100 on DAZ Studio 4)
	// -> heap corruption on startup. QVariantMap and QStringList are safe
	// (their storage is allocated and freed inside QtCore), so arrays here
	// are emitted item by item and never wrapped in a QVariant.
	JsonBuilder json;
	json.startObject();
	json.addMember("schema_version", ServerConfig::CAPABILITIES_SCHEMA_VERSION);

	QVariantMap server;
	server["name"]    = QString("DazScriptServer");
	server["version"] = QString(DZSRV_VERSION_STR);
	server["instance_id"] = QString::fromLatin1(m_serverInstanceId);
	json.addMember("server", QVariant(server));

	QVariantMap studio;
	studio["version"]          = dzApp ? dzApp->getVersionString() : QString();
	studio["sdk_version"]      = QString("%1.%2.%3.%4")
		.arg(DZ_SDK_VERSION_MAJOR).arg(DZ_SDK_VERSION_MINOR)
		.arg(DZ_SDK_VERSION_REV).arg(DZ_SDK_VERSION_BUILD);
	studio["sdk_major"]        = DZ_SDK_VERSION_MAJOR;
	studio["qt_version"]       = QString(qVersion());
	studio["qt_build_version"] = QString(QT_VERSION_STR);
	json.addMember("studio", QVariant(studio));

	// ── Routes ───────────────────────────────────────────────────────────────
	QStringList hashLines;
	json.addKey("routes");
	json.startArray();
	for (size_t i = 0; i < sizeof(kCapabilityRoutes) / sizeof(kCapabilityRoutes[0]); ++i) {
		const CapabilityRoute& r = kCapabilityRoutes[i];
		QVariantMap m;
		m["method"] = QString(r.method);
		m["path"]   = QString(r.path);
		m["auth"]   = r.auth;
		m["kind"]   = QString(r.kind);
		json.addItem(QVariant(m));
		hashLines << QString("route %1 %2").arg(QString(r.method), QString(r.path));
	}
	json.finishArray();

	bool hasPluginRoutes = false;
	json.addKey("plugin_routes");
	json.startArray();
	{
		QMutexLocker lock(&m_pluginRoutesMutex);
		for (int i = 0; i < m_pluginRoutes.size(); ++i) {
			const PluginRoute& r = m_pluginRoutes.at(i);
			QVariantMap m;
			m["method"] = r.method;
			m["path"]   = r.path;
			m["auth"]   = true;
			m["owner"]  = r.receiver ? QString(r.receiver->metaObject()->className()) : QString();
			json.addItem(QVariant(m));
			hasPluginRoutes = true;
			hashLines << QString("plugin %1 %2").arg(r.method, r.path);
		}
	}
	json.finishArray();

	// ── Feature flags ────────────────────────────────────────────────────────
	QVariantMap features;
	features["async"]               = true;   // /execute/async, /requests/*
	features["async_cancel"]        = true;   // DELETE /requests/{id}
	features["async_long_poll"]     = true;   // /requests/{id}/result?wait=true
	features["report_file"]         = true;   // async "reportFile" JSONL job reports
	features["script_registry"]     = true;   // /scripts/*
	features["sse_scene_events"]    = true;   // /scene/events
	features["sse_render_progress"] = true;   // /render/{id}/progress
	features["render"]              = true;
	features["render_batch"]        = true;
	features["render_animation"]    = true;
	features["render_cancel"]       = true;
	features["scene_save_copy"]     = true;
	features["geometry_frames"]     = true;
	features["companion_plugins"]   = hasPluginRoutes;
	features["idempotency_key"]     = true;   // Idempotency-Key on job submission routes
	features["correlation_id"]      = true;   // X-Correlation-Id echoed on job routes + records
	features["server_instance_id"]  = true;   // per-run identity (X-Server-Instance-Id)
	features["scene_revision"]      = true;   // change counter on /status and job responses
	features["error_envelope"]      = true;   // error_code/error/retryable on every failure
	features["artifacts"]           = true;   // GET /artifacts/{id}[/{artifact_id}] downloads
	features["job_activity"]        = true;   // progress_supported/_source, last_activity_at, idle_ms
	features["animation_frame_progress"] = true; // frame N of M in /render/animation job status
	json.addMember("features", QVariant(features));
	for (QVariantMap::const_iterator it = features.begin(); it != features.end(); ++it)
		hashLines << QString("feature %1 %2").arg(it.key(), QString(it.value().toBool() ? "1" : "0"));

	// ── Limits (current settings, not just defaults) ─────────────────────────
	QVariantMap limits;
	limits["max_body_size_mb"]        = m_nMaxBodySizeMB;
	limits["max_script_length_kb"]    = m_nMaxScriptLengthKB;
	limits["max_concurrent_requests"] = m_nMaxConcurrentRequests;
	limits["max_batch_variants"]      = ServerConfig::MAX_BATCH_VARIANTS;
	limits["max_animation_frames"]    = ServerConfig::MAX_ANIMATION_FRAMES;
	limits["async_max_queue_depth"]   = m_pAsyncMgr ? m_pAsyncMgr->maxQueueDepth()
	                                                : AsyncRequestManager::DEFAULT_MAX_QUEUE_DEPTH;
	limits["async_result_ttl_seconds"] = ServerConfig::ASYNC_RESULT_TTL_SEC;
	limits["idempotency_ttl_seconds"]  = m_idempotency.ttlSeconds();
	limits["stale_job_timeout_minutes"] = m_nStaleJobTimeoutMin;
	json.addMember("limits", QVariant(limits));

	QVariantMap rateLimit;
	rateLimit["enabled"]        = m_rateLimiter.isEnabled();
	rateLimit["max_requests"]   = m_pRateLimitMaxSpin ? m_pRateLimitMaxSpin->value()
	                                                  : ServerConfig::DEFAULT_RATE_LIMIT_MAX;
	rateLimit["window_seconds"] = m_pRateLimitWindowSpin ? m_pRateLimitWindowSpin->value()
	                                                     : ServerConfig::DEFAULT_RATE_LIMIT_WINDOW;
	rateLimit["applies_to"]     = QString("write");  // POST/DELETE routes only
	json.addMember("rate_limit", QVariant(rateLimit));

	QVariantMap security;
	security["auth_enabled"]         = m_auth.isEnabled();
	security["auth_headers"]         = QStringList() << "X-API-Token" << "Authorization: Bearer";
	security["ip_whitelist_enabled"] = m_ipWhitelist.isEnabled();
	json.addMember("security", QVariant(security));

	// ── Render engines, read live from DzRenderMgr ───────────────────────────
	json.addKey("render_engines");
	json.startObject();
	QStringList selectable;
	QString activeClass;
	json.addKey("registered");
	json.startArray();
	DzRenderMgr* renderMgr = dzApp ? dzApp->getRenderMgr() : nullptr;
	if (renderMgr) {
		DzRenderer* active = renderMgr->getActiveRenderer();
		if (active) activeClass = QString(active->metaObject()->className());
		for (int i = 0; i < renderMgr->getNumRenderers(); ++i) {
			DzRenderer* r = renderMgr->getRenderer(i);
			if (!r) continue;
			QVariantMap m;
			const QString cls = QString(r->metaObject()->className());
			m["class_name"] = cls;
			m["name"]       = r->getName();
			m["active"]     = (r == active);
			json.addItem(QVariant(m));
		}
		for (size_t i = 0; i < sizeof(kSelectableEngines) / sizeof(kSelectableEngines[0]); ++i) {
			const SelectableEngine& e = kSelectableEngines[i];
			if (!e.rendererClass || renderMgr->findRenderer(QString(e.rendererClass)))
				selectable << QString(e.engine);
		}
	}
	json.finishArray();
	json.addMember("selectable", QVariant(selectable));   // values POST /render accepts for "engine"
	if (activeClass.isEmpty()) json.addMemberNull("active_class");
	else                       json.addMember("active_class", activeClass);
	json.addMember("source", engineSource);              // "live" or "snapshot"
	json.addMember("read_at", QDateTime::currentDateTimeUtc().toString(Qt::ISODate));
	json.finishObject();

	// Stable fingerprint of the API surface: schema, routes (incl. companion
	// routes) and feature flags. Changes in limits, settings or render engines
	// don't change it, so clients can cache their route/feature decisions by it.
	hashLines.prepend(QString("schema %1").arg(ServerConfig::CAPABILITIES_SCHEMA_VERSION));
	hashLines.sort();
	QByteArray digest = QCryptographicHash::hash(hashLines.join("\n").toUtf8(),
	                                             QCryptographicHash::Sha1).toHex();
	json.addMember("compatibility_hash", QString::fromLatin1(digest.left(16)));

	json.finishObject();
	return json.toString().toUtf8();
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
	return DzProgress::isActive() || DzBackgroundProgress::isActive();
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
	if (DzBackgroundProgress::isActive()) {
		return "DAZ Studio is busy loading background content (e.g. lazy-loaded/referenced scene assets)";
	}
	if (DzProgress::isActive()) {
		return "DAZ Studio is showing a progress dialog for a foreground operation";
	}
	return "DAZ Studio is busy";
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
	m_sCurrentRenderId = isRender ? id : QString();
	connect(dzApp, DSS_DEBUG_SIGNAL,
	        this,  SLOT(onMessagePosted(const QString&)),
	        Qt::DirectConnection);

	ensurePersistentScript()->clear();
	ScriptRunResult runResult;
	if (!scriptFile.isEmpty() && !m_pPersistentScript->loadFromFile(scriptFile)) {
		runResult.errorMessage = QString("Failed to load script file: %1").arg(scriptFile);
	} else {
		if (scriptFile.isEmpty())
			m_pPersistentScript->setCode(scriptText);
		runResult = runDazScript(m_pPersistentScript, args, scriptFile);
	}
#if DAZ_SDK_MAJOR_VERSION >= 6
	m_aCapturedLogLines = runResult.output;  // SDK6: evaluate() bypasses the debugMsg signal
#endif

	bool     executed    = runResult.success;
	QVariant scriptResult = runResult.result;
	QString  errorMsg;
	if (!executed) {
		errorMsg = runResult.errorMessage;
		if (runResult.errorLine > 0)
			errorMsg = QString("Line %1: %2").arg(runResult.errorLine).arg(errorMsg);
	}
	QStringList capturedOutput = m_aCapturedLogLines;

	disconnect(dzApp, DSS_DEBUG_SIGNAL,
	           this,  SLOT(onMessagePosted(const QString&)));
	m_bCapturingLog = false;
	m_sCurrentRenderId.clear();

	int durationMs = wallClock.msecsTo(QTime::currentTime());

	// Bump before markCompleted so a client that sees the job finish also
	// sees the revision that covers its effects. A failed script may still
	// have changed the scene before it threw, so bump either way.
	m_sceneRevision.fetchAndAddOrdered(1);

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

// ─── Scene I/O ────────────────────────────────────────────────────────────────

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
