#include "AuthenticationService.h"
#include "SecureRandom.h"

#include <QtCore/qfile.h>
#include <QtCore/qdir.h>
#include <QtCore/qtextstream.h>
#include <QtCore/qfileinfo.h>

#ifndef _WIN32
    #include <sys/stat.h>
#endif

AuthenticationService::AuthenticationService()
    : m_bEnabled(true)
{}

void AuthenticationService::setEnabled(bool enabled)
{
    m_bEnabled = enabled;
}

bool AuthenticationService::isEnabled() const
{
    return m_bEnabled;
}

QString AuthenticationService::generateToken() const
{
    return SecureRandom::generateHexToken(16);  // 16 bytes = 128 bits = 32 hex chars
}

QString AuthenticationService::getTokenFilePath()
{
    QString homeDir = QDir::homePath();
    QString dazDir  = homeDir + "/.daz3d";
    QDir dir;
    if (!dir.exists(dazDir))
        dir.mkpath(dazDir);
    return dazDir + "/dazscriptserver_token.txt";
}

bool AuthenticationService::loadOrGenerateToken(QStringList& outMessages)
{
    QString tokenPath = getTokenFilePath();
    QFile   file(tokenPath);

    if (file.exists()) {
#ifndef _WIN32
        QFileInfo info(tokenPath);
        QFile::Permissions perms = info.permissions();
        if (perms & (QFile::ReadGroup | QFile::WriteGroup |
                     QFile::ReadOther | QFile::WriteOther)) {
            outMessages << QString("[WARN] Token file has insecure permissions — "
                                   "others can read it! File: %1").arg(tokenPath);
            outMessages << QString("[WARN] Run: chmod 600 %1").arg(tokenPath);
        }
#endif
        if (file.open(QIODevice::ReadOnly | QIODevice::Text)) {
            QTextStream in(&file);
#if DAZ_SDK_MAJOR_VERSION < 6
            in.setCodec("UTF-8"); // Qt6 QTextStream is UTF-8 by default; setCodec() was removed
#endif
            QString loaded = in.readLine().trimmed();
            file.close();

            if (!loaded.isEmpty() && loaded.length() >= 32) {
                QByteArray ba = loaded.toUtf8();
                QWriteLocker lock(&m_tokenLock);
                m_sToken    = loaded;
                m_sTokenStr = std::string(ba.constData(), ba.size());
                return true;
            }
            outMessages << "[INFO] Existing token invalid, generating new one";
        }
    } else {
        outMessages << "[INFO] No token file found, generating new secure token";
    }

    QString newToken = generateToken();
    if (newToken.isEmpty()) {
        outMessages << "[ERROR] Failed to generate secure token — crypto API unavailable";
        return false;
    }
    {
        QByteArray ba = newToken.toUtf8();
        QWriteLocker lock(&m_tokenLock);
        m_sToken    = newToken;
        m_sTokenStr = std::string(ba.constData(), ba.size());
    }

    QString saveMsg;
    if (saveToken(saveMsg))
        outMessages << QString("[INFO] Generated new API token saved to %1").arg(tokenPath);
    else
        outMessages << saveMsg;

    return true;
}

bool AuthenticationService::saveToken(QString& outMessage)
{
    QString tokenPath = getTokenFilePath();
    QFile   file(tokenPath);

    QReadLocker lock(&m_tokenLock);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        outMessage = QString("[ERROR] Failed to save token to %1").arg(tokenPath);
        return false;
    }
    QTextStream out(&file);
#if DAZ_SDK_MAJOR_VERSION < 6
    out.setCodec("UTF-8"); // Qt6 QTextStream is UTF-8 by default; setCodec() was removed
#endif
    out << m_sToken << "\n";
    file.close();

#ifndef _WIN32
    if (chmod(tokenPath.toUtf8().constData(), S_IRUSR | S_IWUSR) != 0)
        outMessage = QString("[WARN] Failed to set restrictive permissions on %1").arg(tokenPath);
#else
    outMessage = QString("[INFO] Token saved to %1. On Windows, manually restrict file "
                         "access to your user account only.").arg(tokenPath);
#endif
    return true;
}

static std::string trimStr(const std::string& s)
{
    const char* ws = " \t\r\n";
    size_t start = s.find_first_not_of(ws);
    if (start == std::string::npos) return std::string();
    size_t end = s.find_last_not_of(ws);
    return s.substr(start, end - start + 1);
}

bool AuthenticationService::validateToken(const std::string& providedToken) const
{
    if (providedToken.empty())
        return false;
    std::string trimmed = trimStr(providedToken);
    QReadLocker lock(&m_tokenLock);
    return trimmed == m_sTokenStr;
}

QString AuthenticationService::getToken() const
{
    QReadLocker lock(&m_tokenLock);
    return m_sToken;
}

void AuthenticationService::setToken(const QString& token)
{
    QByteArray ba = token.toUtf8();
    QWriteLocker lock(&m_tokenLock);
    m_sToken    = token;
    m_sTokenStr = std::string(ba.constData(), ba.size());
}
