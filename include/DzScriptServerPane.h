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
