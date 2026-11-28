// Built-in companion-plugin route receiver for live tests; see
// PluginRouteSelfTest.h. DzScriptServerPane::setPluginRouteSelfTest() (in
// PluginRouteBridge.cpp) registers and removes its routes.
#include "PluginRouteSelfTest.h"

#include <QtCore/qstring.h>
#include <QtCore/qvariant.h>

#include "JsonStd.h"

HttpResult PluginRouteSelfTest::echo(const QByteArray& body, const QByteArray& ip)
{
	QVariantMap out;
	out.insert("success", true);
	out.insert("slot", QString("echo"));
	out.insert("body", QString::fromUtf8(body.constData(), body.size()));
	out.insert("ip", QString::fromLatin1(ip.constData(), ip.size()));
	return HttpResult(200, JsonStd::variantToJsonBytes(out));
}

HttpResult PluginRouteSelfTest::badStatus(const QByteArray&, const QByteArray&)
{
	return HttpResult(999, QByteArray("{}"));
}

#include "moc_PluginRouteSelfTest.cpp"
