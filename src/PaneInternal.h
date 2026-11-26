#pragma once
// Private to the DzScriptServerPane translation units (W21 split): the
// shared includes and the small helpers more than one of them uses.
// Nothing outside src/DzScriptServerPane.cpp, PaneUi.cpp, HttpJobRoute.cpp,
// PaneRoutes.cpp, PluginRouteBridge.cpp, ScriptJobs.cpp and RenderJobs.cpp
// should include it.
//
// Include httplib first — it pulls in winsock2.h and Windows macros, which must
// precede windows.h. Other route files include it via RouteUtil.h, also first.
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
#include "ArtifactThumbnail.h"
#include "ArtifactRoutes.h"
#include "Capabilities.h"
#include "RouteUtil.h"
#include "MainThreadCall.h"
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
#include <QtCore/qelapsedtimer.h>
#include <QtCore/qeventloop.h>
#include <QtCore/qfile.h>
#include <QtCore/qfileinfo.h>
#include <QtCore/qdir.h>
#include <QtCore/qmap.h>
#include <QtCore/qmutex.h>
#include "QtCompat.h"   // regex and other Qt4/Qt6 API differences
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

ScriptRunResult runDazScript(DzScript* script, const QVariantMap& argsMap,
                             const QString& scriptFile);

// ─── Route helpers ─────────────────────────────────────────────────────────────

// httplib request -> HttpContext, and HttpContext -> httplib response
// (HttpJobRoute.cpp).
HttpContext toContext(const httplib::Request& req);
void        applyContext(const HttpContext& ctx, httplib::Response& res);

// {"request_id","status":"queued","submitted_at"} for job submissions
// (ScriptJobs.cpp).
HttpResult buildQueuedResponse(const QString& requestId, qint64 submittedAt);
