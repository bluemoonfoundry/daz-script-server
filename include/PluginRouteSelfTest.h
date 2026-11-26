#pragma once
// Built-in companion-plugin route receiver for live tests (ih7u).
//
// Companion plugins are other Studio plugins, so no live test could exercise
// registerPluginRoute() and the catch-all dispatch without building a second
// plugin. DzScriptServerPane::setPluginRouteSelfTest(true) registers the
// routes below against this receiver, through the same public
// registerPluginRoute() a companion plugin calls; false removes them. It is
// Q_INVOKABLE, so a test turns it on with POST /execute, which already runs
// arbitrary script, so this adds nothing reachable without a token.
//
// Routes (unattributed: no companion plugin name, so `check_openapi_parity.py
// --live` treats them as notes, not errors, while a test has them on):
//   GET    /_selftest/plugin-route/:id      echo
//   POST   /_selftest/plugin-route          echo
//   PUT    /_selftest/plugin-route/:id      echo
//   GET    /_selftest/plugin-route-bad      badStatus  (slot returns 999)
//   GET    /_selftest/plugin-route-noslot   (slot name the receiver lacks)
//   GET    /_selftest/plugin-route-gone     (receiver deleted after registering)

#include <QtCore/qobject.h>

#include "HttpResult.h"

class PluginRouteSelfTest : public QObject {
	Q_OBJECT
public:
	explicit PluginRouteSelfTest(QObject* parent = nullptr) : QObject(parent) {}

	// 200 {"success":true,"slot":"echo","body":"<request body as received>",
	//      "ip":"<client ip>"}. body is the raw bytes the slot got, as a JSON
	// string: for a route with :params that's the {"_pathParams","_body"}
	// envelope the bridge builds; otherwise the client's body unchanged.
	Q_INVOKABLE HttpResult echo(const QByteArray& body, const QByteArray& ip);

	// Returns status 999 so the bridge's invalid-status branch can be tested.
	Q_INVOKABLE HttpResult badStatus(const QByteArray& body, const QByteArray& ip);
};
