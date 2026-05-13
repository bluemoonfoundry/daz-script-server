#pragma once
#include <QtCore/qstring.h>
#include <QtCore/qstringlist.h>

// Exact-match IP whitelist. Immutable after parse — no mutex needed during checks.
class IPWhitelistService {
public:
    IPWhitelistService();

    void setEnabled(bool enabled) { m_bEnabled = enabled; }
    bool isEnabled() const        { return m_bEnabled; }

    // Parse a comma-separated list of IPs and store them.
    void setWhitelist(const QString& csvIPs);
    QString getWhitelist() const { return m_sRawList; }

    // Returns true if the IP is allowed (whitelist disabled → always true).
    bool isAllowed(const QString& clientIP) const;

private:
    bool        m_bEnabled;
    QString     m_sRawList;
    QStringList m_aParsedIPs;
};
