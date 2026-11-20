#pragma once
#include <atomic>
#include <string>
#include <vector>
#include <QtCore/qstring.h>

// Exact-match IP whitelist. The parsed list is only rewritten while the server
// is stopped (setWhitelist runs before start), so checks need no mutex. The
// enabled flag is atomic: HTTP threads read it while the main thread writes it.
class IPWhitelistService {
public:
    IPWhitelistService();

    void setEnabled(bool enabled) { m_bEnabled = enabled; }
    bool isEnabled() const        { return m_bEnabled; }

    // Parse a comma-separated list of IPs and store them.
    void setWhitelist(const QString& csvIPs);
    QString getWhitelist() const { return m_sRawList; }

    // Returns true if the IP is allowed (whitelist disabled → always true).
    // Safe to call from any thread — no Qt string allocation/deallocation.
    bool isAllowed(const std::string& clientIP) const;

private:
    std::atomic<bool> m_bEnabled;
    QString     m_sRawList;              // for UI display (main thread only)
    std::vector<std::string> m_aParsedIPs; // for hot-path checking (any thread)
};
