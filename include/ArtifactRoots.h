#pragma once
// Trust boundary for GET /artifacts/{id}/{artifact_id}: which declared output
// files the server may serve.
//
// A job declares its outputs by path, and a script can name any file it can
// read. With the boundary enabled (the default), a file is served only when
// its real path -- read back from the already-open handle, so symlinks,
// junctions and "..": all resolved, and nothing can be swapped in between the
// check and the read -- lies inside one of the allowed root folders. Files
// under the denied folder (~/.daz3d, which holds the API token) are never
// served, even with the boundary disabled.
//
// THREADING: configure() and setDeniedDir() run on the main thread while the
// server is stopped (like IPWhitelistService::setWhitelist); allows() runs on
// httplib worker threads and only reads. The enabled flag is atomic so the
// pane can flip it while the server runs.

#include <atomic>
#include <cstdio>
#include <QtCore/qstring.h>
#include <QtCore/qstringlist.h>

class ArtifactRoots {
public:
    ArtifactRoots();

    void setEnabled(bool enabled) { m_bEnabled = enabled; }
    bool isEnabled() const        { return m_bEnabled; }

    // The default roots: the system temp folder plus the user's Documents,
    // Pictures, Desktop and Downloads folders. Main thread (uses QtGui on
    // Studio 4).
    static QStringList defaultRoots();

    // Parse a ';'-separated folder list (empty = defaultRoots()) and resolve
    // each folder's real path. Folders that don't exist are skipped and
    // reported in outWarnings. Main thread, server stopped.
    void configure(const QString& rawList, QStringList* outWarnings = 0);
    QString rawList() const { return m_sRawList; }

    // Effective roots as given (before resolution), for /capabilities and logs.
    QStringList effectiveRoots() const { return m_aEffective; }

    // Folder whose contents are never served. Main thread, server stopped.
    // Returns false when the folder's real path can't be resolved now; the
    // denial still holds (allows() re-resolves per request and refuses every
    // file while the folder exists but stays unresolvable).
    bool setDeniedDir(const QString& dir);

    // True when the open file may be served. Any thread.
    bool allows(FILE* f) const;

    // Real path of an open file / of an existing folder; empty if unknown.
    // Exposed for tests and diagnostics.
    static QString realPathOf(FILE* f);
    static QString realPathOfDir(const QString& dir);

private:
    static bool isUnder(const QString& path, const QString& root);
    bool deniedDirAllows(const QString& realFilePath) const;

    std::atomic<bool> m_bEnabled;
    QString           m_sRawList;     // main thread only
    QStringList       m_aEffective;   // main thread writes while stopped
    QStringList       m_aResolved;    // read by worker threads
    QString           m_sDeniedRaw;   // as given (cleaned); read by worker threads
    QString           m_sDenied;      // resolved, or empty; read by worker threads
};
