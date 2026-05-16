#pragma once
// Thread-safe std::string JSON utilities.
// No Qt GUI calls — safe to call from HTTP-thread code.
//
// QVariant and QString data access (qstrToStd, variantToJson) are thread-safe
// for read-only use per Qt's documented threading model.
//
// JsonBuilder (include/JsonBuilder.h) provides the same logic for Qt-thread
// code that works with QString. Both share the same escape rules; they are
// intentionally separate because converting between QString and std::string
// on every operation would add unnecessary overhead.

#include <string>
#include <cstdio>
#include <ctime>
#include <QtCore/qstring.h>
#include <QtCore/qvariant.h>
#include <QtCore/qmap.h>

namespace JsonStd {

// QString → std::string via UTF-8.
// Routes through QByteArray so the std::string buffer is allocated by this
// DLL's CRT (ucrtbase) rather than QtCore4's (msvcr100), avoiding cross-CRT
// heap corruption on Windows.
inline std::string qstrToStd(const QString& s)
{
    QByteArray ba = s.toUtf8();
    return std::string(ba.constData(), ba.size());
}

// JSON-escape a UTF-8 std::string.  Control characters below 0x20 that are
// not one of the named escapes are emitted as \uXXXX sequences.
inline std::string escape(const std::string& s)
{
    std::string r;
    r.reserve(s.size() + 4);
    for (size_t i = 0; i < s.size(); ++i) {
        unsigned char c = static_cast<unsigned char>(s[i]);
        if      (c == '"')  r += "\\\"";
        else if (c == '\\') r += "\\\\";
        else if (c == '\n') r += "\\n";
        else if (c == '\r') r += "\\r";
        else if (c == '\t') r += "\\t";
        else if (c < 0x20)  { char esc[8]; std::snprintf(esc, sizeof(esc), "\\u%04x", c); r += esc; }
        else                r += static_cast<char>(c);
    }
    return r;
}

// Recursively serialize a QVariant to a JSON value string.
inline std::string variantToJson(const QVariant& v)
{
    if (!v.isValid() || v.isNull()) return "null";
    switch (v.type()) {
    case QVariant::Bool:
        return v.toBool() ? "true" : "false";
    case QVariant::Int:
    case QVariant::LongLong:
    case QVariant::UInt:
    case QVariant::ULongLong:
        return std::to_string(v.toLongLong());
    case QVariant::Double: {
        char buf[32];
        std::snprintf(buf, sizeof(buf), "%.15g", v.toDouble());
        return buf;
    }
    case QVariant::String:
        return "\"" + escape(qstrToStd(v.toString())) + "\"";
    case QVariant::List:
    case QVariant::StringList: {
        QVariantList list = v.toList();
        std::string s = "[";
        for (int i = 0; i < list.size(); ++i) {
            if (i > 0) s += ",";
            s += variantToJson(list.at(i));
        }
        s += "]";
        return s;
    }
    case QVariant::Map: {
        QVariantMap map = v.toMap();
        std::string s = "{";
        bool first = true;
        for (QVariantMap::const_iterator it = map.begin(); it != map.end(); ++it) {
            if (!first) s += ",";
            first = false;
            s += "\"" + escape(qstrToStd(it.key())) + "\":";
            s += variantToJson(it.value());
        }
        s += "}";
        return s;
    }
    default:
        return "\"" + escape(qstrToStd(v.toString())) + "\"";
    }
}

// Format milliseconds-since-epoch as an ISO 8601 local-time string
// (e.g. "2026-05-15T14:30:00").
inline std::string msecToIso(long long msec)
{
    time_t t = static_cast<time_t>(msec / 1000);
    struct tm tm_val = {};
#ifdef _WIN32
    localtime_s(&tm_val, &t);
#else
    localtime_r(&t, &tm_val);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm_val);
    return buf;
}

// Format the current local time as "HH:MM:SS" (for log line prefixes).
inline std::string currentTime()
{
    time_t t = time(nullptr);
    struct tm tm_val = {};
#ifdef _WIN32
    localtime_s(&tm_val, &t);
#else
    localtime_r(&t, &tm_val);
#endif
    char buf[16];
    std::strftime(buf, sizeof(buf), "%H:%M:%S", &tm_val);
    return buf;
}

} // namespace JsonStd
