// Include httplib ONLY here — it pulls in winsock2.h and Windows macros.
// CPPHTTPLIB_NO_COMPRESS is set via target_compile_definitions in CMakeLists.txt.
#include "httplib.h"

#include "DzScriptServerPane.h"

#include <dzapp.h>
#include <dzscript.h>

#include <QtCore/qmetaobject.h>
#include <QtGui/qboxlayout.h>
#include <QtGui/qformlayout.h>
#include <QtGui/qgroupbox.h>
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
{
	// ── Build UI ─────────────────────────────────────────────────────────────
	QFormLayout* formLayout = new QFormLayout();
	formLayout->setContentsMargins(6, 6, 6, 6);

	m_pHostEdit = new QLineEdit("127.0.0.1", this);
	formLayout->addRow(tr("Host:"), m_pHostEdit);

	m_pPortSpin = new QSpinBox(this);
	m_pPortSpin->setRange(1024, 65535);
	m_pPortSpin->setValue(m_nPort);
	formLayout->addRow(tr("Port:"), m_pPortSpin);

	m_pStatusLabel = new QLabel(tr("Stopped"), this);

	m_pStartBtn = new QPushButton(tr("Start Server"), this);
	m_pStopBtn  = new QPushButton(tr("Stop Server"),  this);
	m_pStopBtn->setEnabled(false);

	QHBoxLayout* btnLayout = new QHBoxLayout();
	btnLayout->addWidget(m_pStartBtn);
	btnLayout->addWidget(m_pStopBtn);

	m_pLogView = new QTextEdit(this);
	m_pLogView->setReadOnly(true);
	m_pLogView->setMaximumHeight(120);

	QVBoxLayout* mainLayout = new QVBoxLayout(this);
	mainLayout->setContentsMargins(4, 4, 4, 4);
	mainLayout->addLayout(formLayout);
	mainLayout->addWidget(m_pStatusLabel);
	mainLayout->addLayout(btnLayout);
	mainLayout->addWidget(m_pLogView);
	mainLayout->addStretch();
	setLayout(mainLayout);

	connect(m_pStartBtn, SIGNAL(clicked()), this, SLOT(onStartClicked()));
	connect(m_pStopBtn,  SIGNAL(clicked()), this, SLOT(onStopClicked()));
}

DzScriptServerPane::~DzScriptServerPane()
{
	stopServer();
}

// ─── Start / Stop ─────────────────────────────────────────────────────────────

void DzScriptServerPane::onStartClicked()
{
	m_nPort = m_pPortSpin->value();
	m_sHost = m_pHostEdit->text();
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

	m_pServer = new httplib::Server();
	m_pServer->set_read_timeout(30, 0);
	setupRoutes();

	m_aHostUtf8 = m_sHost.toUtf8();
	m_pServerThread = new ServerListenThread(
		m_pServer,
		std::string(m_aHostUtf8.constData()),
		m_nPort,
		this);
	m_pServerThread->start();

	m_bRunning = true;
	updateUI();
	appendLog(QString("Server started on %1:%2").arg(m_sHost).arg(m_nPort));
}

void DzScriptServerPane::stopServer()
{
	if (!m_bRunning)
		return;

	if (m_pServer) {
		m_pServer->stop();
		m_pServer = nullptr;
	}
	if (m_pServerThread) {
		m_pServerThread->wait(5000);
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
		m_pStatusLabel->setText(tr("Running on %1:%2").arg(m_sHost).arg(m_nPort));
		m_pStartBtn->setEnabled(false);
		m_pStopBtn->setEnabled(true);
		m_pHostEdit->setEnabled(false);
		m_pPortSpin->setEnabled(false);
	} else {
		m_pStatusLabel->setText(tr("Stopped"));
		m_pStartBtn->setEnabled(true);
		m_pStopBtn->setEnabled(false);
		m_pHostEdit->setEnabled(true);
		m_pPortSpin->setEnabled(true);
	}
}

void DzScriptServerPane::appendLog(const QString& line)
{
	if (m_pLogView)
		m_pLogView->append(line);
}

// ─── Route setup ──────────────────────────────────────────────────────────────
//
// THREADING RULE: httplib invokes these handlers on raw std::threads (not QThreads).
// Handlers must do NO Qt work beyond constructing/copying QByteArray.
// All Qt work happens in handleExecuteRequest() on the main thread via
// Qt::BlockingQueuedConnection.

void DzScriptServerPane::setupRoutes()
{
	m_pServer->Get("/status", [](const httplib::Request&, httplib::Response& res) {
		res.set_content("{\"running\":true,\"version\":\"1.0.0.0\"}",
		                "application/json");
	});

	m_pServer->Post("/execute", [this](const httplib::Request& req, httplib::Response& res) {
		QByteArray bodyBytes(req.body.c_str(), (int)req.body.size());
		QByteArray responseBytes;

		QMetaObject::invokeMethod(
			this, "handleExecuteRequest",
			Qt::BlockingQueuedConnection,
			Q_RETURN_ARG(QByteArray, responseBytes),
			Q_ARG(QByteArray, bodyBytes));

		res.set_content(responseBytes.constData(), responseBytes.size(),
		                "application/json");
	});
}

// ─── Main-thread request handler ──────────────────────────────────────────────

QByteArray DzScriptServerPane::handleExecuteRequest(const QByteArray& jsonBody)
{
	// Parse JSON body (QScriptEngine is a QObject — only safe on a Qt-managed thread)
	QString      bodyStr = QString::fromUtf8(jsonBody.constData(), jsonBody.size());
	QScriptEngine parseEngine;
	QScriptValue  parsed   = parseEngine.evaluate("(" + bodyStr + ")");
	QVariantMap   bodyMap  = parsed.toVariant().toMap();

	QString     scriptFile = bodyMap.value("scriptFile").toString();
	QString     scriptText = bodyMap.value("script").toString();
	QVariantMap argsMap    = bodyMap.value("args").toMap();

	if (scriptFile.isEmpty() && scriptText.isEmpty()) {
		QString resp = buildResponseJson(false, QVariant(), QStringList(),
		                                 QVariant(QString("Either scriptFile or script is required")));
		return resp.toUtf8();
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
			                                 QVariant(QString("Failed to load scriptFile: %1").arg(scriptFile)));
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

	// Log a summary line in the pane
	QString logLabel = scriptFile.isEmpty()
		? scriptText.left(60).replace('\n', ' ')
		: scriptFile.left(60);
	appendLog(QString("[%1] %2").arg(success ? "OK" : "ERR").arg(logLabel));

	QString resp = buildResponseJson(success,
	                                 success ? scriptResult : QVariant(),
	                                 m_aCapturedLogLines,
	                                 errorVar);
	return resp.toUtf8();
}

void DzScriptServerPane::onMessagePosted(const QString& msg)
{
	if (m_bCapturingLog)
		m_aCapturedLogLines.append(msg);
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
                                              const QVariant& error)
{
	QVariantList outputList;
	foreach (const QString& line, output)
		outputList.append(QVariant(line));

	QString json;
	json += "{";
	json += "\"success\":"  + QString(success ? "true" : "false") + ",";
	json += "\"result\":"   + variantToJson(result)                + ",";
	json += "\"output\":"   + variantToJson(QVariant(outputList))  + ",";
	json += "\"error\":"    + variantToJson(error);
	json += "}";
	return json;
}

#include "moc_DzScriptServerPane.cpp"
