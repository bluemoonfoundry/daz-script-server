// DzScriptServerPane: httplib request/response <-> HttpContext, and the job
// route pipeline (runJobRoute / runSyncJobRoute). Runs on httplib worker
// threads; see the threading rule above setupRoutes() in PaneRoutes.cpp.
#include "PaneInternal.h"

// ─── Route helpers ───────────────────────────────────────────────────────────

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

HttpContext toContext(const httplib::Request& req)
{
	HttpContext ctx;
	ctx.body       = req.body;
	ctx.remoteAddr = req.remote_addr.empty() ? "unknown" : req.remote_addr;
	if (req.matches.size() > 1)
		ctx.urlMatch = req.matches[1].str();
	if (req.is_connection_closed)
		ctx.isClientGone = req.is_connection_closed;
	ctx.headers["x-api-token"]  = req.get_header_value("X-API-Token");
	ctx.headers["authorization"] = req.get_header_value("Authorization");
	ctx.headers["idempotency-key"]  = req.get_header_value("Idempotency-Key");
	ctx.headers["x-correlation-id"] = req.get_header_value("X-Correlation-Id");
	for (httplib::Params::const_iterator it = req.params.begin();
	     it != req.params.end(); ++it)
		ctx.queryParams[it->first] = it->second;
	return ctx;
}

void applyContext(const HttpContext& ctx, httplib::Response& res)
{
	// A status outside 100-599 (e.g. a handler that never answered) would make
	// httplib send no response at all.
	if (ctx.responseStatus < 100 || ctx.responseStatus > 599) {
		res.status = 500;
		res.set_content(ErrorResponse::build(ErrorCode::INTERNAL_ERROR, "handler produced no valid HTTP status"),
		                "application/json");
		return;
	}
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
			ctx.setHeader("Retry-After", ServerConfig::RETRY_AFTER_IN_FLIGHT_SEC);
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

// Synchronous job routes (/execute, /scripts/:id/execute) hold one of the
// m_nMaxConcurrentRequests slots for the whole request; when none is free the
// request is refused with 429 before anything else runs. Not idempotent: a
// retry runs the script again, so clients that need retry safety use the async
// routes with an Idempotency-Key.
void DzScriptServerPane::runSyncJobRoute(const httplib::Request& req, httplib::Response& res,
                                         IRequestHandler* handler)
{
	ActiveRequestSlot slot(m_nActiveRequests, m_nMaxConcurrentRequests);
	if (!slot) {
		res.status = 429;
		res.set_content(ErrorResponse::build(ErrorCode::CONCURRENT_LIMIT_EXCEEDED), "application/json");
		return;
	}
	QMetaObject::invokeMethod(this, "updateActiveRequestsLabel", Qt::QueuedConnection);
	runJobRoute(req, res, handler, false);
	QMetaObject::invokeMethod(this, "updateActiveRequestsLabel", Qt::QueuedConnection);
}
