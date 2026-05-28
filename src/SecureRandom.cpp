#include "SecureRandom.h"
#include <QtCore/qdebug.h>

#ifdef _WIN32
    #include <windows.h>
    #include <wincrypt.h>
    // RtlGenRandom (SystemFunction036) — available since Windows XP, no context required
    #define RtlGenRandom SystemFunction036
    extern "C" BOOLEAN NTAPI RtlGenRandom(PVOID RandomBuffer, ULONG RandomBufferLength);
    #pragma comment(lib, "advapi32.lib")
#else
    #include <fstream>
    #include <unistd.h>
    #include <errno.h>
    #ifdef __linux__
        #include <sys/syscall.h>
    #endif
#endif

static const int MAX_RETRIES = 3;

QByteArray SecureRandom::generateBytes(int count)
{
    if (count <= 0) {
        qWarning("SecureRandom::generateBytes: Invalid count %d", count);
        return QByteArray();
    }

    QByteArray randomBytes(count, 0);

#ifdef _WIN32
    // ─── Windows: CryptoAPI with RtlGenRandom fallback ───────────────────────
    for (int attempt = 1; attempt <= MAX_RETRIES; ++attempt) {
        HCRYPTPROV hProvider = 0;
        if (!CryptAcquireContext(&hProvider, NULL, NULL, PROV_RSA_FULL,
                                 CRYPT_VERIFYCONTEXT | CRYPT_SILENT)) {
            DWORD err = GetLastError();
            qWarning("SecureRandom: CryptAcquireContext failed (attempt %d/%d), error 0x%lx",
                     attempt, MAX_RETRIES, err);
            if (attempt < MAX_RETRIES) {
                Sleep(10 * attempt);
                continue;
            }
            // All CryptoAPI attempts exhausted — fall through to RtlGenRandom
            break;
        }

        BOOL ok = CryptGenRandom(hProvider, (DWORD)count, (BYTE*)randomBytes.data());
        DWORD err = ok ? 0 : GetLastError();
        CryptReleaseContext(hProvider, 0);

        if (ok)
            return randomBytes;

        qWarning("SecureRandom: CryptGenRandom failed (attempt %d/%d), error 0x%lx",
                 attempt, MAX_RETRIES, err);
        if (attempt < MAX_RETRIES)
            Sleep(10 * attempt);
    }

    // Fallback: RtlGenRandom (SystemFunction036) — simpler, no context needed
    qWarning("SecureRandom: Falling back to RtlGenRandom");
    if (RtlGenRandom((PVOID)randomBytes.data(), (ULONG)count))
        return randomBytes;

    qWarning("SecureRandom: RtlGenRandom also failed — crypto unavailable");
    return QByteArray();

#else
    // ─── Unix/macOS: /dev/urandom with /dev/random fallback ──────────────────
    for (int attempt = 1; attempt <= MAX_RETRIES; ++attempt) {
        std::ifstream urandom("/dev/urandom", std::ios::binary);
        if (!urandom.is_open()) {
            qWarning("SecureRandom: Cannot open /dev/urandom (attempt %d/%d)", attempt, MAX_RETRIES);
            if (attempt < MAX_RETRIES) {
                usleep(10000 * attempt);
                continue;
            }
            break;
        }

        urandom.read(randomBytes.data(), count);
        bool ok = urandom.good();
        urandom.close();

        if (ok)
            return randomBytes;

        qWarning("SecureRandom: Failed to read %d bytes from /dev/urandom (attempt %d/%d)",
                 count, attempt, MAX_RETRIES);
        if (attempt < MAX_RETRIES)
            usleep(10000 * attempt);
    }

    // Fallback: /dev/random (blocking but always available)
    qWarning("SecureRandom: Falling back to /dev/random");
    std::ifstream devRandom("/dev/random", std::ios::binary);
    if (devRandom.is_open()) {
        devRandom.read(randomBytes.data(), count);
        bool ok = devRandom.good();
        devRandom.close();
        if (ok)
            return randomBytes;
        qWarning("SecureRandom: /dev/random read failed");
    } else {
        qWarning("SecureRandom: Cannot open /dev/random");
    }

    return QByteArray();
#endif
}

QString SecureRandom::generateHexToken(int byteCount)
{
    QByteArray randomBytes = generateBytes(byteCount);

    if (randomBytes.isEmpty()) {
        qWarning("SecureRandom::generateHexToken: Failed to generate random bytes");
        return QString();
    }

    return QString(randomBytes.toHex());
}
