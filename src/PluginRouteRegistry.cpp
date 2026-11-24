// Split out of DzScriptServerPane.cpp (x7ul.32); see PluginRouteRegistry.h.
#include "PluginRouteRegistry.h"
#include <QtCore/qstringlist.h>

bool PluginRouteRegistry::isValidName(const QString& name)
{
	if (name.isEmpty() || name.size() > 64) return false;
	for (int i = 0; i < name.size(); ++i) {
		const QChar c = name.at(i);
		const bool ok = (c >= QLatin1Char('a') && c <= QLatin1Char('z'))
			|| (c >= QLatin1Char('A') && c <= QLatin1Char('Z'))
			|| (c >= QLatin1Char('0') && c <= QLatin1Char('9'))
			|| c == QLatin1Char('.') || c == QLatin1Char('_') || c == QLatin1Char('-');
		if (!ok) return false;
	}
	return true;
}

bool PluginRouteRegistry::isValidVersion(const QString& version)
{
	if (version.isEmpty() || version.size() > 64) return false;
	for (int i = 0; i < version.size(); ++i) {
		const ushort u = version.at(i).unicode();
		if (u < 0x21 || u > 0x7e) return false;  // printable ASCII, no spaces
	}
	return true;
}

bool PluginRouteRegistry::registerCompanion(const QString& name, const QString& version,
                                            const QString& description)
{
	if (!isValidName(name) || !isValidVersion(version))
		return false;
	Companion p;
	p.name        = name;
	p.version     = version;
	p.description = description.left(500);
	QMutexLocker lock(&m_mutex);
	for (int i = 0; i < m_companions.size(); ++i) {
		if (m_companions[i].name == name) {
			m_companions[i] = p;
			return true;
		}
	}
	m_companions.append(p);
	return true;
}

void PluginRouteRegistry::unregisterCompanion(const QString& name)
{
	QMutexLocker lock(&m_mutex);
	for (int i = m_companions.size() - 1; i >= 0; --i)
		if (m_companions[i].name == name)
			m_companions.removeAt(i);
	for (int i = m_routes.size() - 1; i >= 0; --i)
		if (m_routes[i].plugin == name)
			m_routes.removeAt(i);
}

bool PluginRouteRegistry::registerRoute(const QString& method, const QString& path,
                                        QObject* receiver, const QString& slotName,
                                        const QString& pluginName, QString* outMethod)
{
	if (!receiver || path.isEmpty() || slotName.isEmpty())
		return false;

	const QString m = method.toUpper();
	if (m != "GET" && m != "POST" && m != "PUT" && m != "DELETE" && m != "PATCH")
		return false;
	if (outMethod) *outMethod = m;

	Route r;
	r.method   = m;
	r.path     = path;
	r.receiver = receiver;
	r.slotName = slotName;
	r.plugin   = pluginName;

	QMutexLocker lock(&m_mutex);
	if (!pluginName.isEmpty()) {
		bool known = false;
		for (int i = 0; i < m_companions.size(); ++i)
			if (m_companions[i].name == pluginName) { known = true; break; }
		if (!known) {
			Companion p;
			p.name = pluginName;
			m_companions.append(p);
		}
	}
	for (int i = 0; i < m_routes.size(); ++i) {
		if (m_routes[i].method == m && m_routes[i].path == path) {
			m_routes[i] = r;
			return true;
		}
	}
	m_routes.append(r);
	return true;
}

void PluginRouteRegistry::unregisterRoute(const QString& method, const QString& path)
{
	const QString m = method.toUpper();
	QMutexLocker lock(&m_mutex);
	for (int i = 0; i < m_routes.size(); ++i) {
		if (m_routes[i].method == m && m_routes[i].path == path) {
			m_routes.removeAt(i);
			return;
		}
	}
}

// Match a path-pattern (e.g. "/export/usd/:id") against a concrete path.
// Fills `params` with captured segment values keyed by the param name (no colon).
// Returns true on match.  Both arguments must start with '/'.
bool PluginRouteRegistry::matchPath(const QString& pattern, const QString& path,
                                    QMap<QString, QString>& params)
{
	const QStringList patParts  = pattern.split('/');
	const QStringList pathParts = path.split('/');
	if (patParts.size() != pathParts.size()) return false;
	params.clear();
	for (int i = 0; i < patParts.size(); ++i) {
		if (patParts[i].startsWith(':'))
			params[patParts[i].mid(1)] = pathParts[i];
		else if (patParts[i] != pathParts[i])
			return false;
	}
	return true;
}

bool PluginRouteRegistry::match(const QString& method, const QString& path,
                                QPointer<QObject>* outReceiver, QByteArray* outSlot,
                                QMap<QString, QString>* outParams) const
{
	QMutexLocker lock(&m_mutex);
	for (int i = 0; i < m_routes.size(); ++i) {
		const Route& r = m_routes[i];
		if (r.method != method) continue;
		if (!matchPath(r.path, path, *outParams)) continue;
		*outReceiver = r.receiver;
		*outSlot     = r.slotName.toLatin1();
		return true;
	}
	return false;
}

void PluginRouteRegistry::snapshot(QList<Route>* outRoutes, QList<Companion>* outCompanions) const
{
	QMutexLocker lock(&m_mutex);
	if (outRoutes)     *outRoutes     = m_routes;
	if (outCompanions) *outCompanions = m_companions;
}
