#pragma once
#include <memory>
#include <string>
#include <dzpane.h>
#include <QtCore/qpair.h>
#include <QtCore/qthread.h>
#include <QtCore/qstringlist.h>
#include <QtCore/qvariant.h>
#include <QtCore/qbytearray.h>
#include <QtCore/qatomic.h>
#include <QtCore/qmutex.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qtimer.h>
#include <QtCore/qmetatype.h>
#include <QtGui/qspinbox.h>
#include <QtGui/qlineedit.h>
#include <QtGui/qpushbutton.h>
#include <QtGui/qlabel.h>
#include <QtGui/qtextedit.h>
#include <QtGui/qcheckbox.h>
#include <QtGui/qgroupbox.h>

#include "AuthenticationService.h"
#include "RateLimiterService.h"
#include "IPWhitelistService.h"
#include "MetricsCollector.h"
#include "RequestHandler.h"
#include "AsyncRequestManager.h"

// Required for BlockingQueuedConnection return from execute/register handlers.
typedef QPair<int, QByteArray> HttpResult;
Q_DECLARE_METATYPE(HttpResult)

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
	// Returns HttpResult (status, jsonBody) so handlers can set the correct HTTP status code.
	Q_INVOKABLE HttpResult handleExecuteRequest(const QByteArray& jsonBody, const QByteArray& clientIP);
	Q_INVOKABLE HttpResult handleRegisterScript(const QByteArray& jsonBody, const QByteArray& clientIP);
	Q_INVOKABLE HttpResult handleRegistryExecuteRequest(const QByteArray& scriptText, const QByteArray& scriptId, const QByteArray& requestBody, const QByteArray& clientIP);

	void appendLog(const QString& line);
	void updateActiveRequestsLabel();

public:
	// Observability — called from HTTP threads (thread-safe via internal mutexes/atomics)
	QString getHealthJson() const;
	QString getMetricsJson() const;

	// Script Registry operations — called from HTTP threads (mutex-protected)
	QString              listScriptsJson() const;
	QPair<int, QString>  deleteRegistryScriptJson(const QString& id, const QString& clientIP);
	bool                 lookupRegistryScript(const QString& id, QString& outScript) const;

	// Async request management — called from HTTP threads (delegated to AsyncRequestManager)
	QString              enqueueAsyncRequest(const QString& scriptText, const QVariantMap& args,
	                                         const QString& idPrefix, qint64& outSubmittedAt,
	                                         QString& outError);
	QPair<int, QString>  getAsyncStatusJson(const QString& requestId) const;
	QPair<int, QString>  getAsyncResultJson(const QString& requestId, bool doWait, int timeoutSec);
	QPair<int, QString>  cancelAsyncRequestJson(const QString& requestId, const QString& clientIP);
	QString              listAsyncRequestsJson(const QString& statusFilter) const;

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

	// Async execution (runs on main thread via Qt event loop)
	void processNextAsyncRequest();
	void cleanupExpiredRequests();
	void killRenderOnMainThread();

private:
	void   setupRoutes();
	void   updateUI();
	QString variantToJson(const QVariant& v);
	QString buildResponseJson(bool success,
	                          const QVariant& result,
	                          const QStringList& output,
	                          const QVariant& error,
	                          const QString& requestId = QString());

	void    loadSettings();
	void    saveSettings();

	// Server state
	httplib::Server* m_pServer;
	QThread*         m_pServerThread;   // actually a ServerListenThread*
	int              m_nPort;
	QString          m_sHost;
	QByteArray       m_aHostUtf8;
	bool             m_bRunning;
	int              m_nTimeoutSec;
	bool             m_bAutoStart;

	// Configurable limits
	int              m_nMaxConcurrentRequests;
	int              m_nMaxBodySizeMB;
	int              m_nMaxScriptLengthKB;

	// Log capture during script execution
	QStringList m_aCapturedLogLines;
	bool        m_bCapturingLog;

	// ── Service objects ───────────────────────────────────────────────────────
	AuthenticationService m_auth;
	RateLimiterService    m_rateLimiter;
	IPWhitelistService    m_ipWhitelist;
	MetricsCollector      m_metrics;

	QAtomicInt       m_nActiveRequests;  // Current concurrent requests (atomic: written from HTTP threads)

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
	//   HTTP threads: call enqueueAsyncRequest() / getAsyncStatusJson() / etc.,
	//                 which delegate to AsyncRequestManager (mutex-protected).
	//   Main thread:  processNextAsyncRequest() dequeues and executes serially.
	//                 All DzScript execution happens here, same as sync path.
	//
	// IMPORTANT: processNextAsyncRequest() blocks the main thread (and thus the
	// Qt event loop) for the full duration of each script execution.  That is
	// intentional — DAZ Studio's API is single-threaded.  Status queries are
	// served directly from AsyncRequestManager's mutex-protected map without
	// needing the main thread, so polling always returns promptly.

	AsyncRequestManager* m_pAsyncMgr;
	QTimer*              m_pCleanupTimer; // Fires every 5 min to purge TTL-expired requests

	// ── Middleware chains (created in setupRoutes) ────────────────────────────
	std::unique_ptr<MiddlewareChain> m_pAuthChain;         // auth only
	std::unique_ptr<MiddlewareChain> m_pExecuteSyncChain;  // IP + rate + body_size + auth
	std::unique_ptr<MiddlewareChain> m_pBaseExecuteChain;  // IP + rate + auth

	// ── Request handlers (created in setupRoutes) ─────────────────────────────
	std::unique_ptr<StatusHandler>        m_pStatusHandler;
	std::unique_ptr<HealthHandler>        m_pHealthHandler;
	std::unique_ptr<MetricsHandler>       m_pMetricsHandler;
	std::unique_ptr<ExecuteScriptHandler> m_pExecuteHandler;
	std::unique_ptr<ScriptRegisterHandler> m_pRegisterHandler;
	std::unique_ptr<ScriptListHandler>    m_pScriptListHandler;
	std::unique_ptr<ScriptDeleteHandler>  m_pScriptDeleteHandler;
	std::unique_ptr<ScriptExecuteHandler> m_pScriptExecHandler;
	std::unique_ptr<AsyncExecuteHandler>  m_pAsyncExecHandler;
	std::unique_ptr<AsyncScriptHandler>   m_pAsyncScriptHandler;
	std::unique_ptr<AsyncStatusHandler>   m_pAsyncStatusHandler;
	std::unique_ptr<AsyncResultHandler>   m_pAsyncResultHandler;
	std::unique_ptr<AsyncCancelHandler>   m_pAsyncCancelHandler;
	std::unique_ptr<AsyncListHandler>     m_pAsyncListHandler;

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
