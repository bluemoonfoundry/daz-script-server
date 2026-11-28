#pragma once
// (status, JSON body) returned by request handlers and companion-plugin route
// slots. Metatype needed to pass it through queued calls and invokeMethod().
#include <QtCore/qbytearray.h>
#include <QtCore/qmetatype.h>
#include <QtCore/qpair.h>

typedef QPair<int, QByteArray> HttpResult;
Q_DECLARE_METATYPE(HttpResult)
