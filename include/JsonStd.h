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
#include <QtCore/qbytearray.h>

#if DAZ_SDK_MAJOR_VERSION >= 6
#include <QtCore/qjsondocument.h>
#include <QtCore/qjsonobject.h>
#else
// Qt 4.8 (bundled with the DAZStudio 4.5+ SDK) has no QJsonDocument — it's a
// Qt 5.0+ class. Fall back to QtScript, same as the rest of the DS4 build.
#include <QtScript/qscriptengine.h>
#include <QtScript/qscriptvalue.h>
#endif

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

// Convenience wrapper: variantToJson() as a QByteArray, ready to write to a
// file or use as an HTTP request/response body. Added for the Package Runner
// epic (daz-script-server-5sw); ported back from daz-python-bridge's copy of
// this header, which itself started as a fork of this file.
inline QByteArray variantToJsonBytes(const QVariant& v)
{
    const std::string s = variantToJson(v);
    return QByteArray(s.data(), static_cast<int>(s.size()));
}

#if DAZ_SDK_MAJOR_VERSION >= 6

// Parse a JSON object body into a QVariantMap. QJsonDocument::fromJson is
// reentrant and has no QObject/thread affinity, so this is safe to call from
// any thread.
// Returns false and fills errorDetail with a human-readable message on
// failure (object expected at the top level counts as failure too).
inline bool parseObject(const QByteArray& jsonBody, QVariantMap& out, std::string& errorDetail)
{
    QJsonParseError err;
    QJsonDocument doc = QJsonDocument::fromJson(jsonBody, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) {
        char buf[32];
        std::snprintf(buf, sizeof(buf), "offset %d: ", err.offset);
        errorDetail = buf + qstrToStd(err.error != QJsonParseError::NoError
            ? err.errorString() : QString("expected a JSON object"));
        return false;
    }
    out = doc.object().toVariantMap();
    return true;
}

#else

// Parse a JSON object body into a QVariantMap via QtScript's JS evaluator
// (Qt 4.8 has no QJsonDocument). QScriptEngine is a QObject, so — unlike the
// Qt6 overload above — this must only be called on the Qt main thread.
// Returns false and fills errorDetail with a human-readable message on
// failure (object expected at the top level counts as failure too).
inline bool parseObject(const QByteArray& jsonBody, QVariantMap& out, std::string& errorDetail)
{
    QString bodyStr = QString::fromUtf8(jsonBody.constData(), jsonBody.size());
    QScriptEngine parseEngine;
    QScriptValue parsed = parseEngine.evaluate("(" + bodyStr + ")");
    if (parseEngine.hasUncaughtException()) {
        char buf[32];
        std::snprintf(buf, sizeof(buf), "line %d: ", parseEngine.uncaughtExceptionLineNumber());
        errorDetail = buf + qstrToStd(parseEngine.uncaughtException().toString());
        return false;
    }
    if (!parsed.isObject()) {
        errorDetail = "expected a JSON object";
        return false;
    }
    out = parsed.toVariant().toMap();
    return true;
}

#endif

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
