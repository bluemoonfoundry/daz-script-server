#pragma once
// Routes and companion plugins registered by other Studio plugins through
// DzScriptServerPane::registerPluginRoute()/registerCompanionPlugin().
//
// THREADING: every method locks the internal mutex. Registration runs on the
// main thread (companion plugins call the pane there, or through a blocking
// queued call); match() runs on httplib worker threads for every request that
// reaches the catch-all handlers, so routes registered after the server
// started are seen without touching httplib's handler vectors.

#include <QtCore/qbytearray.h>
#include <QtCore/qlist.h>
#include <QtCore/qmap.h>
#include <QtCore/qmutex.h>
#include <QtCore/qobject.h>
#include <QtCore/qpointer.h>
#include <QtCore/qstring.h>

class PluginRouteRegistry {
public:
    struct Route {
        QString           method;    // "GET", "POST", "PUT", "DELETE", "PATCH"
        QString           path;      // may contain ":param" segments
        QPointer<QObject> receiver;
        QString           slotName;  // Q_INVOKABLE: HttpResult slotName(QByteArray, QByteArray)
        QString           plugin;    // companion plugin name; empty if unattributed
    };
    struct Companion {
        QString name;
        QString version;      // empty when only routes named it
        QString description;
    };

    // Companion names: 1-64 of [A-Za-z0-9._-]. Versions: 1-64 printable ASCII.
    static bool isValidName(const QString& name);
    static bool isValidVersion(const QString& version);

    // Add or update a companion plugin; false (nothing changed) if invalid.
    bool registerCompanion(const QString& name, const QString& version,
                           const QString& description);
    // Remove the companion plugin and every route it registered.
    void unregisterCompanion(const QString& name);

    // Add or replace (same method + path) a route. *pluginName* may be empty
    // (unattributed); a non-empty name not yet registered is added without a
    // version. False (nothing changed) for a null receiver, empty path or
    // slot, or an unsupported method. *outMethod* receives the upper-cased method.
    bool registerRoute(const QString& method, const QString& path, QObject* receiver,
                       const QString& slotName, const QString& pluginName,
                       QString* outMethod = 0);
    void unregisterRoute(const QString& method, const QString& path);

    // First route for *method* whose pattern matches *path*. On a match fills
    // the receiver, the slot name (Latin-1) and the ":param" captures.
    bool match(const QString& method, const QString& path, QPointer<QObject>* outReceiver,
               QByteArray* outSlot, QMap<QString, QString>* outParams) const;

    // Copies of both lists, for /capabilities (main thread).
    void snapshot(QList<Route>* outRoutes, QList<Companion>* outCompanions) const;

private:
    static bool matchPath(const QString& pattern, const QString& path,
                          QMap<QString, QString>& params);

    QList<Route>     m_routes;
    QList<Companion> m_companions;
    mutable QMutex   m_mutex;
};
