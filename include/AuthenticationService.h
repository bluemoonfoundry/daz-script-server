#pragma once
#include <QtCore/qstring.h>
#include <QtCore/qstringlist.h>
#include <QtCore/qreadwritelock.h>
#include <string>

// Manages API token generation, persistence, and validation.
// Thread-safe: validateToken() may be called from HTTP threads.
class AuthenticationService {
public:
    AuthenticationService();

    void setEnabled(bool enabled);
    bool isEnabled() const;

    // Loads existing token or generates a new one.
    // Returns false if crypto API is unavailable.
    // outMessages receives log lines the caller should display.
    bool loadOrGenerateToken(QStringList& outMessages);

    // Returns false on failure; outMessage receives a log line to display.
    bool saveToken(QString& outMessage);

    // Thread-safe — may be called from HTTP threads.
    bool validateToken(const std::string& providedToken) const;

    QString getToken() const;
    void    setToken(const QString& token);

    static QString getTokenFilePath();

private:
    QString generateToken() const;

    bool    m_bEnabled;
    QString m_sToken;
    mutable QReadWriteLock m_tokenLock;
};
