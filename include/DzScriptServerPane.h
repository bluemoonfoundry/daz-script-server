#pragma once
#include <string>
#include <dzpane.h>
#include <QtCore/qthread.h>
#include <QtCore/qstringlist.h>
#include <QtCore/qvariant.h>
#include <QtCore/qbytearray.h>
#include <QtCore/qmutex.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qtimer.h>
#include <QtCore/qqueue.h>
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
    // Configurable defaults
    const int DEFAULT_MAX_CONCURRENT_REQUESTS = 10;
    const int DEFAULT_MAX_BODY_SIZE_MB = 5;
    const int DEFAULT_MAX_SCRIPT_LENGTH_KB = 1024;  // 1MB in KB
    const int DEFAULT_RATE_LIMIT_MAX = 60;
    const int DEFAULT_RATE_LIMIT_WINDOW = 60;

    // Fixed internal constants
    const int MAX_LOG_LINES = 1000;
    const int MAX_CAPTURED_LINES = 10000;
    const int RATE_LIMIT_CLEANUP_INTERVAL = 100;
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
	Q_INVOKABLE QByteArray handleRegisterScript(const QByteArray& jsonBody, const QByteArray& clientIP);
	Q_INVOKABLE QByteArray handleRegistryExecuteRequest(const QByteArray& scriptText, const QByteArray& scriptId, const QByteArray& requestBody, const QByteArray& clientIP);

private slots:
	void onStartClicked();
	void onStopClicked();
	void onMessagePosted(const QString& msg);
	void onCopyTokenClicked();
	void onRegenTokenClicked();
	void onAuthEnabledChanged(int state);
	void onClearLogClicked();
	void onIpWhitelistEnabledChanged(int state);
	void onRateLimitEnabledChanged(int state);
	void onAutoStartChanged(int state);
	void updateActiveRequestsLabel();

	// Async execution (runs on main thread via Qt event loop)
	void processNextAsyncRequest();
	void cleanupExpiredRequests();

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
	void    saveMetrics();
	QString getHealthJson() const;
	QString getMetricsJson() const;

	// IP Whitelist and Rate Limiting
	void    parseWhitelistIPs();
	bool    isIPWhitelisted(const QString& clientIP) const;
	bool    checkRateLimit(const QString& clientIP);
	void    cleanupRateLimitMap();

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
	bool             m_bAutoStart;

	// Configurable limits
	int              m_nMaxConcurrentRequests;
	int              m_nMaxBodySizeMB;
	int              m_nMaxScriptLengthKB;

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
		mutable QMutex mutex;  // Protects the counters

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

	// Rate limit tracking structure
	struct RateLimitInfo {
		QList<qint64> timestamps;  // Unix timestamps in seconds
		RateLimitInfo() {}
	};

	struct RateLimitState {
		QMap<QString, RateLimitInfo> ipMap;
		QMutex mutex;
		int cleanupCounter;
		RateLimitState() : cleanupCounter(0) {}
	};

	// Script Registry (session-only, in-memory)
	struct RegisteredScript {
		QString   description;
		QString   script;
		QDateTime registeredAt;
	};
	struct ScriptRegistry {
		QMap<QString, RegisteredScript> scripts;
		mutable QMutex mutex;
	};
	ScriptRegistry m_scriptRegistry;

	// ── Async Request Infrastructure ─────────────────────────────────────────
	//
	// THREADING MODEL:
	//   HTTP threads: enqueue requests (under mutex), read status/result (under
	//                 mutex), set cancelRequested (under mutex).
	//   Main thread:  processNextAsyncRequest() dequeues and executes serially.
	//                 All DzScript execution happens here, same as sync path.
	//
	// IMPORTANT: processNextAsyncRequest() blocks the main thread (and thus the
	// Qt event loop) for the full duration of each script execution.  This is
	// intentional — DAZ Studio's API is single-threaded.  Status queries are
	// served directly from the mutex-protected map without needing the main
	// thread, so polling always returns promptly even during a long render.

	enum RequestStatus {
		REQUEST_QUEUED,
		REQUEST_RUNNING,
		REQUEST_COMPLETED,
		REQUEST_FAILED,
		REQUEST_CANCELLED
	};

	struct AsyncRequest {
		AsyncRequest()
			: status(REQUEST_QUEUED)
			, scriptExecuted(false)
			, progress(0.0)
			, submittedAt(0), startedAt(0), completedAt(0)
			, cancelRequested(0)
		{}

		QString       id;
		RequestStatus status;
		QString       scriptText;     // Resolved script body (inline or from registry)
		QVariantMap   args;

		// Set after execution completes
		QVariant      scriptResult;   // From DzScript::result()
		QStringList   outputLines;    // Captured dzApp debugMsg output
		QString       error;          // Error string (failed/cancelled)
		bool          scriptExecuted; // true if DzScript::execute() succeeded

		// Progress and timing (milliseconds since epoch)
		double  progress;     // 0.0–1.0; -1.0 = unknown
		qint64  submittedAt;
		qint64  startedAt;
		qint64  completedAt;

		// Cancel flag — always read/written while holding AsyncState::mutex
		int cancelRequested;
	};

	struct AsyncState {
		QMap<QString, AsyncRequest> requests;
		QQueue<QString>             queue;     // IDs of QUEUED requests (FIFO)
		QString                     currentId; // ID of RUNNING request; empty = idle
		mutable QMutex              mutex;
	};
	AsyncState  m_async;
	QTimer*     m_pCleanupTimer;  // Fires every 5 min to purge TTL-expired requests

	// Private helper methods for async
	QString     generateAsyncId(const QString& type) const;
	std::string requestStatusToString(RequestStatus status) const;

	// IP Whitelist state (immutable after server start - no mutex needed)
	bool             m_bIpWhitelistEnabled;
	QString          m_sIpWhitelist;       // Comma-separated list
	QStringList      m_aWhitelistIPs;      // Parsed list

	// Rate limiting state (mutex-protected)
	bool             m_bRateLimitEnabled;
	int              m_nRateLimitMax;
	int              m_nRateLimitWindowSec;
	RateLimitState   m_rateLimitState;

	// UI widgets
	QLineEdit*   m_pHostEdit;
	QSpinBox*    m_pPortSpin;
	QSpinBox*    m_pTimeoutSpin;
	QPushButton* m_pStartBtn;
	QPushButton* m_pStopBtn;
	QLabel*      m_pStatusLabel;
	QLabel*      m_pActiveRequestsLabel;
	QTextEdit*   m_pLogView;
	QPushButton* m_pClearLogBtn;

	// Authentication UI
	QCheckBox*   m_pAuthEnabledCheck;
	QLineEdit*   m_pTokenEdit;
	QPushButton* m_pCopyTokenBtn;
	QPushButton* m_pRegenTokenBtn;
	QCheckBox*   m_pAutoStartCheck;

	// IP Whitelist UI
	QCheckBox*   m_pIpWhitelistCheck;
	QLineEdit*   m_pIpWhitelistEdit;

	// Rate Limiting UI
	QCheckBox*   m_pRateLimitCheck;
	QSpinBox*    m_pRateLimitMaxSpin;
	QSpinBox*    m_pRateLimitWindowSpin;

	// Advanced Limits UI
	QSpinBox*    m_pMaxConcurrentSpin;
	QSpinBox*    m_pMaxBodySizeSpin;
	QSpinBox*    m_pMaxScriptLengthSpin;
};
