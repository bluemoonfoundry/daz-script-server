#include "IPWhitelistService.h"
#include <QtCore/qstringlist.h>
#include <string>

static inline std::string qstrToStr(const QString& s)
{
    QByteArray ba = s.toUtf8();
    return std::string(ba.constData(), ba.size());
}

IPWhitelistService::IPWhitelistService()
    : m_bEnabled(false)
    , m_sRawList("127.0.0.1")
{}

void IPWhitelistService::setWhitelist(const QString& csvIPs)
{
    m_sRawList = csvIPs;
    m_aParsedIPs.clear();

    if (csvIPs.isEmpty())
        return;

    QStringList raw = csvIPs.split(',', QString::SkipEmptyParts);
    foreach (const QString& ip, raw) {
        QString trimmed = ip.trimmed();
        if (!trimmed.isEmpty())
            m_aParsedIPs.push_back(qstrToStr(trimmed));
    }
}

bool IPWhitelistService::isAllowed(const std::string& clientIP) const
{
    if (!m_bEnabled)
        return true;
    if (m_aParsedIPs.empty())
        return false;  // Enabled but no IPs configured — block all
    for (size_t i = 0; i < m_aParsedIPs.size(); ++i)
        if (m_aParsedIPs[i] == clientIP) return true;
    return false;
}
