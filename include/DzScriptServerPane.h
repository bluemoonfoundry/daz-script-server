#pragma once
#include <string>
#include <dzpane.h>
#include <QtCore/qthread.h>
#include <QtCore/qstringlist.h>
#include <QtCore/qvariant.h>
#include <QtCore/qbytearray.h>
#include <QtCore/qmutex.h>
#include <QtCore/qdatetime.h>
#include <QtGui/qspinbox.h>
#include <QtGui/qlineedit.h>
#include <QtGui/qpushbutton.h>
#include <QtGui/qlabel.h>
#include <QtGui/qtextedit.h>
#include <QtGui/qcheckbox.h>
#include <QtGui/qgroupbox.h>

// Forward-declare httplib::Server — httplib.h included only in DzScriptServerPane.cpp
namespace httplib { class Server; }

// ─── Configuration Constants ──────────────────────────────────────────────────

namespace ServerConfig {
    const int MAX_CONCURRENT_REQUESTS = 10;     // Max simultaneous requests
    const size_t MAX_BODY_SIZE = 5 * 1024 * 1024;  // 5MB request body limit
    const int MAX_SCRIPT_LENGTH = 1024 * 1024;   // 1MB script text limit
    const int MAX_LOG_LINES = 1000;              // Max UI log lines
    const int MAX_CAPTURED_LINES = 10000;        // Max captured output lines
}

class DzScriptServerPane : public DzPane {
	Q_OBJECT
	Q_PROPERTY(int     nPort    READ getPort    WRITE setPort)
	Q_PROPERTY(QString sHost    READ getHost    WRITE setHost)
	Q_PROPERTY(bool    bRunning READ isRunning)

public:
	DzScriptServerPane();
	~DzScriptServerPane();

	Q_INVOKABLE int     getPort()  const { return m_nPort; }
	Q_INVOKABLE void    setPort(int p)   { m_nPort = p; }
	Q_INVOKABLE QString getHost()  const { return m_sHost; }
	Q_INVOKABLE void    setHost(const QString& h) { m_sHost = h; }
	Q_INVOKABLE bool    isRunning() const { return m_bRunning; }

public slots:
	Q_INVOKABLE void startServer();
	Q_INVOKABLE void stopServer();

	// Called on main thread via BlockingQueuedConnection from httplib handler threads.
	Q_INVOKABLE QByteArray handleExecuteRequest(const QByteArray& jsonBody, const QByteArray& clientIP);

private slots:
	void onStartClicked();
	void onStopClicked();
	void onMessagePosted(const QString& msg);
	void onCopyTokenClicked();
	void onRegenTokenClicked();
	void onAuthEnabledChanged(int state);
	void onClearLogClicked();

private:
	void   setupRoutes();
	void   updateUI();
	void   appendLog(const QString& line);
	QString variantToJson(const QVariant& v);
	QString buildResponseJson(bool success,
	                          const QVariant& result,
	                          const QStringList& output,
	                          const QVariant& error,
	                          const QString& requestId = QString());

	// Authentication
	QString generateToken();
	void    loadOrGenerateToken();
	void    saveToken();
	void    loadSettings();
	void    saveSettings();
	bool    validateToken(const std::string& providedToken) const;

	// Metrics and monitoring
	QString generateRequestId();
	void    recordRequest(bool success, qint64 durationMs);
	QString getHealthJson() const;
	QString getMetricsJson() const;

	// Server state
	httplib::Server* m_pServer;
	QThread*         m_pServerThread;   // actually a ServerListenThread*
	int              m_nPort;
	QString          m_sHost;
	QByteArray       m_aHostUtf8;
	bool             m_bRunning;
	int              m_nTimeoutSec;

	// Authentication
	QString          m_sApiToken;
	bool             m_bAuthEnabled;

	// Log capture during script execution
	QStringList m_aCapturedLogLines;
	bool        m_bCapturingLog;

	// Request management and metrics
	struct RequestMetrics {
		int         totalRequests;
		int         successfulRequests;
		int         failedRequests;
		int         authFailures;
		QDateTime   startTime;
		QMutex      mutex;  // Protects the counters

		RequestMetrics()
			: totalRequests(0)
			, successfulRequests(0)
			, failedRequests(0)
			, authFailures(0)
			, startTime(QDateTime::currentDateTime())
		{}
	};
	RequestMetrics   m_metrics;
	int              m_nActiveRequests;  // Current concurrent requests

	// UI widgets
	QLineEdit*   m_pHostEdit;
	QSpinBox*    m_pPortSpin;
	QSpinBox*    m_pTimeoutSpin;
	QPushButton* m_pStartBtn;
	QPushButton* m_pStopBtn;
	QLabel*      m_pStatusLabel;
	QTextEdit*   m_pLogView;
	QPushButton* m_pClearLogBtn;

	// Authentication UI
	QCheckBox*   m_pAuthEnabledCheck;
	QLineEdit*   m_pTokenEdit;
	QPushButton* m_pCopyTokenBtn;
	QPushButton* m_pRegenTokenBtn;
};
