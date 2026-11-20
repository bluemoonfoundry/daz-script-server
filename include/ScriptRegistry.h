#pragma once
// Session-only, in-memory store behind POST /scripts/register, GET /scripts,
// DELETE /scripts/{id} and POST /scripts/{id}/execute|async.
//
// THREADING: every method locks the internal mutex. registerScript() runs on
// the main thread (it is reached through the JSON handler there); list/remove/
// lookup run on httplib worker threads.
//
// CRT: keys are QByteArray (not QString) so worker threads can look up
// scripts without creating QString temporaries that ~QString would free via
// the wrong CRT (ucrtbase vs msvcr100 on Studio 4). Results cross back as
// std::string built with JsonStd helpers, never QString::toStdString().

#include <string>
#include <QtCore/qbytearray.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qmap.h>
#include <QtCore/qmutex.h>
#include <QtCore/qstring.h>

class ScriptRegistry {
public:
    // Insert or overwrite *name*. Returns true when it replaced an entry;
    // *outRegisteredAt* receives the new entry's timestamp.
    bool registerScript(const QString& name, const QString& description,
                        const QString& script, QDateTime* outRegisteredAt);

    // {"scripts":[{name,description,registered_at}...],"count":N}
    std::string listJson() const;

    // False when *id* was not registered.
    bool remove(const std::string& id);

    // False when *id* is not registered; otherwise *outScript* is its source.
    bool lookup(const std::string& id, std::string& outScript) const;

private:
    struct Entry {
        QString   description;
        QString   script;
        QDateTime registeredAt;
    };
    QMap<QByteArray, Entry> m_scripts;
    mutable QMutex          m_mutex;
};
