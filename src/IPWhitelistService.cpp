#include "IPWhitelistService.h"

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
            m_aParsedIPs.append(trimmed);
    }
}

bool IPWhitelistService::isAllowed(const QString& clientIP) const
{
    if (!m_bEnabled)
        return true;
    if (m_aParsedIPs.isEmpty())
        return false;  // Enabled but no IPs configured — block all
    return m_aParsedIPs.contains(clientIP);
}
