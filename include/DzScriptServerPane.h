#pragma once
#include <memory>
#include <string>
#include <utility>
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
#include <QtCore/qpointer.h>
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
#include "SettingsService.h"
#include "ServerSettings.h"
#include "SceneEventBroker.h"
#include "RenderProgressBroker.h"

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

    // Server lifecycle timing
    const int SERVER_BIND_WAIT_MS = 100;           // Wait after listen() before checking is_running()
    const int SERVER_THREAD_STOP_TIMEOUT_MS = 5000; // Max wait for server thread to join on stop
    const int HTTP_KEEP_ALIVE_MAX_COUNT = 5;        // Max requests per persistent connection
    const int HTTP_KEEP_ALIVE_TIMEOUT_SEC = 5;      // Keep-alive idle timeout in seconds

    // Async request management
    const int ASYNC_CLEANUP_INTERVAL_MIN = 5;       // How often to purge TTL-expired async requests
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

	// Plugin route registration — called by companion plugins loaded in the same process.
	// Registers method+path on the httplib server immediately (or at next server start if
	// the server is not yet running).
	// receiver must expose slotName as Q_INVOKABLE with signature HttpResult(QByteArray,QByteArray).
	Q_INVOKABLE bool registerPluginRoute(const QString& method, const QString& path,
	                                     QObject* receiver, const QString& slotName);
	Q_INVOKABLE void unregisterPluginRoute(const QString& method, const QString& path);

public slots:
	Q_INVOKABLE void startServer();
	Q_INVOKABLE void stopServer();

	// Called on main thread via BlockingQueuedConnection from httplib handler threads.
	// Returns HttpResult (status, jsonBody) so handlers can set the correct HTTP status code.
	Q_INVOKABLE HttpResult handleExecuteRequest(const QByteArray& jsonBody, const QByteArray& clientIP);
	Q_INVOKABLE HttpResult handleRegisterScript(const QByteArray& jsonBody, const QByteArray& clientIP);
	Q_INVOKABLE HttpResult handleRegistryExecuteRequest(const QByteArray& scriptText, const QByteArray& scriptId, const QByteArray& requestBody, const QByteArray& clientIP);

	// Async enqueue helpers — called on main thread via BlockingQueuedConnection from
	// AsyncExecuteHandler / AsyncScriptHandler so that QScriptEngine and QString work
	// stays on the Qt main thread.
	Q_INVOKABLE HttpResult handleAsyncExecuteEnqueue(const QByteArray& jsonBody);
	Q_INVOKABLE HttpResult handleAsyncScriptEnqueue(const QByteArray& scriptBytes,
	                                                const QByteArray& scriptIdBytes,
	                                                const QByteArray& bodyBytes);
	Q_INVOKABLE HttpResult handleAsyncRenderEnqueue(const QByteArray& jsonBody);
	Q_INVOKABLE HttpResult handleAsyncRenderBatchEnqueue(const QByteArray& jsonBody);

	// Scene I/O helpers — called on main thread via BlockingQueuedConnection.
	Q_INVOKABLE HttpResult handleSaveCopy(const QByteArray& jsonBody);

	void appendLog(const QString& line);
	// Worker-thread-safe: accepts log data as QByteArray (whose ~QByteArray calls qFree,
	// not ::free, so it is safe to construct/destroy on httplib worker threads).
	void appendLogBytes(const QByteArray& data);
	void updateActiveRequestsLabel();
	void updateEventClientsLabel();

public:
	// Observability — called from HTTP threads (thread-safe; no Qt string ops on worker threads)
	std::string getHealthJson() const;
	std::string getMetricsJson() const;

	// Script Registry operations — called from HTTP threads (mutex-protected, no Qt string ops)
	std::string                 listScriptsJson() const;
	std::pair<int, std::string> deleteRegistryScriptJson(const std::string& id, const std::string& clientIP);
	bool                        lookupRegistryScript(const std::string& id, std::string& outScript) const;

	// Async request management — called from HTTP threads (delegated to AsyncRequestManager)
	// enqueueAsyncRequest still takes Qt types (used by Tier-1 async handlers — fix pending)
	QString              enqueueAsyncRequest(const QString& scriptText, const QVariantMap& args,
	                                         const QString& idPrefix, qint64& outSubmittedAt,
	                                         QString& outError);
	std::pair<int, std::string> getAsyncStatusJson(const std::string& requestId) const;
	std::pair<int, std::string> getAsyncResultJson(const std::string& requestId, bool doWait, int timeoutSec);
	std::pair<int, std::string> cancelAsyncRequestJson(const std::string& requestId, const std::string& clientIP);
	std::pair<int, std::string> cancelRenderRequestJson(const std::string& requestId, const std::string& clientIP);
	std::string                 listAsyncRequestsJson(const std::string& statusFilter) const;

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
	void   applyPluginRoutes();
	void   updateUI();
	QString buildResponseJson(bool success,
	                          const QVariant& result,
	                          const QStringList& output,
	                          const QVariant& error,
	                          const QString& requestId = QString());

	void    loadSettings();
	void    saveSettings();
	void    applySettings(const ServerSettings& s);

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

	// ── Settings service ─────────────────────────────────────────────────────
	SettingsService       m_settingsService;

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
		// Key is QByteArray (not QString) so worker threads can look up scripts
		// without creating QString temporaries that ~QString would free via the
		// wrong CRT (ucrtbase vs msvcr100).
		QMap<QByteArray, RegisteredScript> scripts;
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

	// Plugin route registry — populated by companion plugins via registerPluginRoute().
	// Applied in setupRoutes() each time the server starts.
	struct PluginRoute {
		QString          method;    // "GET", "POST", "PUT", "DELETE", "PATCH"
		QString          path;
		QPointer<QObject> receiver;
		QString          slotName;  // Q_INVOKABLE: HttpResult slotName(QByteArray, QByteArray)
	};
	QList<PluginRoute> m_pluginRoutes;
	mutable QMutex     m_pluginRoutesMutex;

	AsyncRequestManager*  m_pAsyncMgr;
	QTimer*               m_pCleanupTimer;    // Fires every 5 min to purge TTL-expired requests
	SceneEventBroker*     m_pEventBroker;     // SSE scene-change notification broker
	RenderProgressBroker* m_pRenderProgress;  // SSE render progress notification broker

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
	std::unique_ptr<RenderHandler>        m_pRenderHandler;
	std::unique_ptr<RenderBatchHandler>   m_pRenderBatchHandler;
	std::unique_ptr<RenderCancelHandler>  m_pRenderCancelHandler;
	std::unique_ptr<SaveCopyHandler>      m_pSaveCopyHandler;

	// UI widgets
	QLineEdit*   m_pHostEdit;
	QSpinBox*    m_pPortSpin;
	QSpinBox*    m_pTimeoutSpin;
	QPushButton* m_pStartBtn;
	QPushButton* m_pStopBtn;
	QLabel*      m_pStatusLabel;
	QLabel*      m_pActiveRequestsLabel;
	QLabel*      m_pEventClientsLabel;
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
