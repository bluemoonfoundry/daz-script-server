// DzScriptServerPane: widgets, log view, settings load/save and UI slots.
// Main thread only.
#include "PaneInternal.h"

// ─── Pane widgets ──────────────────────────────────────────────────────────────
// Called once from the constructor, after settings are loaded.
void DzScriptServerPane::buildUi()
{
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
	m_pPortSpin->setRange(ServerConfig::PORT_RANGE.min, ServerConfig::PORT_RANGE.max);
	m_pPortSpin->setValue(m_nPort);
	formLayout->addRow(tr("Port:"), m_pPortSpin);

	m_pQueueTimeoutSpin = new QSpinBox(this);
	m_pQueueTimeoutSpin->setRange(ServerConfig::QUEUE_TIMEOUT_SEC_RANGE.min, ServerConfig::QUEUE_TIMEOUT_SEC_RANGE.max);
	m_pQueueTimeoutSpin->setSuffix(tr(" sec"));
	m_pQueueTimeoutSpin->setValue(m_nQueueTimeoutSec);
	m_pQueueTimeoutSpin->setToolTip(tr("How long a synchronous request waits for DAZ Studio's main thread "
		"before it is refused as busy (503). Async jobs are not affected."));
	formLayout->addRow(tr("Queue timeout:"), m_pQueueTimeoutSpin);

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

	// ─── Artifact folders ─────────────────────────────────────────────────
	QGroupBox* artifactGroup = new QGroupBox(tr("Artifact Folders"), this);
	QVBoxLayout* artifactLayout = new QVBoxLayout(artifactGroup);

	m_pArtifactRootsCheck = new QCheckBox(tr("Only serve artifacts from these folders"), this);
	m_pArtifactRootsCheck->setChecked(m_artifactRoots.isEnabled());
	artifactLayout->addWidget(m_pArtifactRootsCheck);

	QHBoxLayout* artifactInputLayout = new QHBoxLayout();
	artifactInputLayout->addWidget(new QLabel(tr("Folders (;-separated):"), this));
	m_pArtifactRootsEdit = new QLineEdit(this);
	m_pArtifactRootsEdit->setText(m_artifactRoots.rawList());
	m_pArtifactRootsEdit->setPlaceholderText(
		tr("Default: temp, Documents, Pictures, Desktop, Downloads"));
	m_pArtifactRootsEdit->setToolTip(ArtifactRoots::defaultRoots().join("\n"));
	artifactInputLayout->addWidget(m_pArtifactRootsEdit);
	artifactLayout->addLayout(artifactInputLayout);

	QLabel* artifactHint = new QLabel(
		tr("GET /artifacts refuses declared outputs outside these folders (symlinks resolved). "
		   "~/.daz3d is always refused."),
		this);
	artifactHint->setWordWrap(true);
	artifactHint->setStyleSheet("QLabel { color: gray; font-size: 9pt; }");
	artifactLayout->addWidget(artifactHint);

	// ─── Rate Limiting ────────────────────────────────────────────────────
	QGroupBox* rateLimitGroup = new QGroupBox(tr("Rate Limiting"), this);
	QVBoxLayout* rateLimitLayout = new QVBoxLayout(rateLimitGroup);

	m_pRateLimitCheck = new QCheckBox(tr("Enable Per-IP Rate Limiting"), this);
	m_pRateLimitCheck->setChecked(m_rateLimiter.isEnabled());
	rateLimitLayout->addWidget(m_pRateLimitCheck);

	QFormLayout* rateLimitFormLayout = new QFormLayout();

	m_pRateLimitMaxSpin = new QSpinBox(this);
	m_pRateLimitMaxSpin->setRange(ServerConfig::RATE_LIMIT_MAX_RANGE.min, ServerConfig::RATE_LIMIT_MAX_RANGE.max);
	m_pRateLimitMaxSpin->setValue(ServerConfig::DEFAULT_RATE_LIMIT_MAX);
	m_pRateLimitMaxSpin->setSuffix(tr(" requests"));
	rateLimitFormLayout->addRow(tr("Max Requests:"), m_pRateLimitMaxSpin);

	m_pRateLimitWindowSpin = new QSpinBox(this);
	m_pRateLimitWindowSpin->setRange(ServerConfig::RATE_LIMIT_WINDOW_RANGE.min, ServerConfig::RATE_LIMIT_WINDOW_RANGE.max);
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
	m_pMaxConcurrentSpin->setRange(ServerConfig::MAX_CONCURRENT_REQUESTS_RANGE.min, ServerConfig::MAX_CONCURRENT_REQUESTS_RANGE.max);
	m_pMaxConcurrentSpin->setValue(m_nMaxConcurrentRequests);
	m_pMaxConcurrentSpin->setSuffix(tr(" concurrent"));
	limitsFormLayout->addRow(tr("Max Concurrent Requests:"), m_pMaxConcurrentSpin);

	m_pMaxBodySizeSpin = new QSpinBox(this);
	m_pMaxBodySizeSpin->setRange(ServerConfig::MAX_BODY_SIZE_MB_RANGE.min, ServerConfig::MAX_BODY_SIZE_MB_RANGE.max);
	m_pMaxBodySizeSpin->setValue(m_nMaxBodySizeMB);
	m_pMaxBodySizeSpin->setSuffix(tr(" MB"));
	limitsFormLayout->addRow(tr("Max Request Body Size:"), m_pMaxBodySizeSpin);

	m_pMaxScriptLengthSpin = new QSpinBox(this);
	m_pMaxScriptLengthSpin->setRange(ServerConfig::MAX_SCRIPT_LENGTH_KB_RANGE.min, ServerConfig::MAX_SCRIPT_LENGTH_KB_RANGE.max);
	m_pMaxScriptLengthSpin->setValue(m_nMaxScriptLengthKB);
	m_pMaxScriptLengthSpin->setSuffix(tr(" KB"));
	limitsFormLayout->addRow(tr("Max Script Length:"), m_pMaxScriptLengthSpin);

	QLabel* limitsHint = new QLabel(
		tr("Resource limits for request processing (restart server to apply)"), this);
	limitsHint->setStyleSheet("QLabel { color: gray; font-size: 9pt; }");
	limitsFormLayout->addRow(limitsHint);

	m_pStaleTimeoutSpin = new QSpinBox(this);
	m_pStaleTimeoutSpin->setRange(ServerConfig::ASYNC_STALE_RUNNING_TIMEOUT_RANGE_MIN.min,
	                              ServerConfig::ASYNC_STALE_RUNNING_TIMEOUT_RANGE_MIN.max);
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
	mainLayout->addWidget(artifactGroup);
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
	connect(m_pArtifactRootsCheck, SIGNAL(stateChanged(int)), this, SLOT(onArtifactRootsEnabledChanged(int)));
	connect(m_pRateLimitCheck, SIGNAL(stateChanged(int)), this, SLOT(onRateLimitEnabledChanged(int)));
	connect(m_pAutoStartCheck, SIGNAL(stateChanged(int)), this, SLOT(onAutoStartChanged(int)));
	connect(m_pStaleTimeoutSpin, SIGNAL(valueChanged(int)), this, SLOT(onStaleTimeoutChanged(int)));
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
		m_pQueueTimeoutSpin->setEnabled(false);
		m_pAuthEnabledCheck->setEnabled(false);
		m_pRegenTokenBtn->setEnabled(false);
		m_pIpWhitelistCheck->setEnabled(false);
		m_pIpWhitelistEdit->setEnabled(false);
		m_pArtifactRootsEdit->setEnabled(false);
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
		m_pQueueTimeoutSpin->setEnabled(true);
		m_pAuthEnabledCheck->setEnabled(true);
		m_pRegenTokenBtn->setEnabled(true);
		m_pIpWhitelistCheck->setEnabled(true);
		m_pIpWhitelistEdit->setEnabled(true);
		m_pArtifactRootsEdit->setEnabled(true);
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

void DzScriptServerPane::postLog(const std::string& line)
{
    const std::string stamped = "[" + JsonStd::currentTime() + "] " + line;
    QMetaObject::invokeMethod(this, "appendLogBytes", Qt::QueuedConnection,
        Q_ARG(QByteArray, stdToQBA(stamped)));
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
	m_nQueueTimeoutSec       = s.queueTimeoutSec;
	m_bAutoStart             = s.autoStart;
	m_nMaxConcurrentRequests = s.maxConcurrentRequests;
	m_nMaxBodySizeMB         = s.maxBodySizeMB;
	m_nMaxScriptLengthKB     = s.maxScriptLengthKB;
	m_nStaleJobTimeoutMin    = s.staleJobTimeoutMin;

	m_auth.setEnabled(s.authEnabled);

	m_ipWhitelist.setEnabled(s.ipWhitelistEnabled);
	m_ipWhitelist.setWhitelist(s.ipWhitelist);

	// Resolved (and any missing folders logged) in startServer().
	m_artifactRoots.setEnabled(s.artifactRootsEnabled);
	m_artifactRoots.configure(s.artifactRoots);

	m_rateLimiter.setEnabled(s.rateLimitEnabled);
	m_rateLimiter.configure(s.rateLimitMax, s.rateLimitWindow);
}

void DzScriptServerPane::saveSettings()
{
	ServerSettings s;
	s.host                  = m_sHost;
	s.port                  = m_nPort;
	s.queueTimeoutSec       = m_nQueueTimeoutSec;
	s.autoStart             = m_bAutoStart;
	s.maxConcurrentRequests = m_nMaxConcurrentRequests;
	s.maxBodySizeMB         = m_nMaxBodySizeMB;
	s.maxScriptLengthKB     = m_nMaxScriptLengthKB;
	s.staleJobTimeoutMin    = m_nStaleJobTimeoutMin;
	s.authEnabled           = m_auth.isEnabled();
	s.ipWhitelistEnabled    = m_ipWhitelist.isEnabled();
	s.ipWhitelist           = m_ipWhitelist.getWhitelist();
	s.artifactRootsEnabled  = m_artifactRoots.isEnabled();
	s.artifactRoots         = m_artifactRoots.rawList();
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

void DzScriptServerPane::onArtifactRootsEnabledChanged(int state)
{
	// Live: the flag is atomic, and the folder list was resolved at start.
	m_artifactRoots.setEnabled(state == Qt::Checked);
	saveSettings();
	if (m_bRunning) {
		appendLog(m_artifactRoots.isEnabled()
			? QString("[INFO] Artifact folders enforced: %1").arg(m_artifactRoots.effectiveRoots().join("; "))
			: QString("[WARN] Artifact folder restriction disabled - any declared output can be served (~/.daz3d still refused)"));
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
