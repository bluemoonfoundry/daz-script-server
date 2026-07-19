#pragma once

#include <dzbasicdialog.h>

#include <QMap>
#include <QString>
#include <QVariant>

class QFormLayout;
class QLineEdit;
class QWidget;

// Builds a form dynamically from a .dzpkg manifest's "inputs" array (see
// package_runner/MANIFEST_SCHEMA.md) and collects the user's values on
// accept, for DzPackageImporter to pass into dsp_runner as the package's
// run(inputs) argument. Only constructed for interactive packages
// (manifest.interactive == true); non-interactive packages skip this
// entirely and run with inputs = {}.
//
// One widget per declared input, keyed by the input's own "type":
//   int    -> QSpinBox (range from min/max)
//   float  -> QDoubleSpinBox (range from min/max, increment from step)
//   string -> QLineEdit
//   bool   -> QCheckBox
//   enum   -> QComboBox (populated from options)
//   file   -> QLineEdit + a "Browse..." button opening QFileDialog::getOpenFileName
class DzPackageInputsDialog : public DzBasicDialog {
	Q_OBJECT
public:
	// inputsSchema is the manifest's "inputs" array, as parsed by JsonStd
	// into a QVariantList of QVariantMap entries (name/label/type/default/
	// min/max/step/options/filter -- see MANIFEST_SCHEMA.md).
	DzPackageInputsDialog(QWidget *parent, const QString &packageDisplayName, const QVariantList &inputsSchema);

	// Valid after the dialog has been exec()'d and accepted -- walks the
	// widget map built in the constructor and reads each one's current
	// value back out, keyed by the input's "name".
	QVariantMap collectedInputs() const;

private slots:
	void onBrowseFileClicked();

private:
	void addInputRow(const QVariantMap &inputSpec);

	// One entry per declared input, keyed by name. The QVariant stored
	// alongside each widget records that input's declared "type", so
	// collectedInputs() knows how to read the right widget property back
	// without re-parsing the schema.
	struct InputWidget {
		QWidget *widget = nullptr;
		QString  type;
	};
	QMap<QString, InputWidget> m_inputWidgets;

	// Populated lazily by onBrowseFileClicked(); maps the "Browse..." button
	// that was clicked back to the QLineEdit it should fill in.
	QMap<QObject *, QLineEdit *> m_browseTargets;

	// Set once in the constructor; addInputRow() appends to this directly
	// rather than digging through layout()->itemAt(...), which would be
	// fragile against DzBasicDialog's own internal layout structure.
	QFormLayout *m_form = nullptr;
};
