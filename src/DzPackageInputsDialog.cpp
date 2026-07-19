#include "DzPackageInputsDialog.h"

#if DAZ_SDK_MAJOR_VERSION >= 6
#include <QtWidgets/qboxlayout.h>
#include <QtWidgets/qcheckbox.h>
#include <QtWidgets/qcombobox.h>
#include <QtWidgets/qfiledialog.h>
#include <QtWidgets/qformlayout.h>
#include <QtWidgets/qlabel.h>
#include <QtWidgets/qlineedit.h>
#include <QtWidgets/qpushbutton.h>
#include <QtWidgets/qspinbox.h>
#else
#include <QtGui/qboxlayout.h>
#include <QtGui/qcheckbox.h>
#include <QtGui/qcombobox.h>
#include <QtGui/qfiledialog.h>
#include <QtGui/qformlayout.h>
#include <QtGui/qlabel.h>
#include <QtGui/qlineedit.h>
#include <QtGui/qpushbutton.h>
#include <QtGui/qspinbox.h>
#endif

namespace {

// QSpinBox/QDoubleSpinBox default to a [0, 99] / [0.0, 99.99] range if never
// told otherwise; treat a manifest input with no "min"/"max" as "no limit"
// by falling back to a generously wide range instead.
const int kDefaultIntMin = -1000000000;
const int kDefaultIntMax = 1000000000;
const double kDefaultFloatMin = -1.0e12;
const double kDefaultFloatMax = 1.0e12;

} // namespace

DzPackageInputsDialog::DzPackageInputsDialog(QWidget *parent, const QString &packageDisplayName, const QVariantList &inputsSchema)
	: DzBasicDialog(parent, packageDisplayName)
{
	setAcceptButtonText("Run");
	setCancelButtonText("Cancel");
	showApplyButton(false);

	QLabel *titleLabel = new QLabel(packageDisplayName, this);
	addWidget(titleLabel);

	m_form = new QFormLayout();
	addLayout(m_form);

	for (const QVariant &entry : inputsSchema) {
		addInputRow(entry.toMap());
	}
}

void DzPackageInputsDialog::addInputRow(const QVariantMap &inputSpec) {
	const QString name = inputSpec.value("name").toString();
	const QString label = inputSpec.value("label").toString();
	const QString type = inputSpec.value("type").toString();
	if (name.isEmpty()) {
		return;  // malformed entry; DzPackageImporter already validated the manifest before getting here
	}

	QWidget *inputWidget = nullptr;

	if (type == "int") {
		QSpinBox *spin = new QSpinBox(this);
		spin->setRange(
			inputSpec.contains("min") ? inputSpec.value("min").toInt() : kDefaultIntMin,
			inputSpec.contains("max") ? inputSpec.value("max").toInt() : kDefaultIntMax);
		spin->setValue(inputSpec.value("default").toInt());
		inputWidget = spin;
	} else if (type == "float") {
		QDoubleSpinBox *spin = new QDoubleSpinBox(this);
		spin->setRange(
			inputSpec.contains("min") ? inputSpec.value("min").toDouble() : kDefaultFloatMin,
			inputSpec.contains("max") ? inputSpec.value("max").toDouble() : kDefaultFloatMax);
		if (inputSpec.contains("step")) {
			spin->setSingleStep(inputSpec.value("step").toDouble());
		}
		spin->setDecimals(4);
		spin->setValue(inputSpec.value("default").toDouble());
		inputWidget = spin;
	} else if (type == "bool") {
		QCheckBox *check = new QCheckBox(this);
		check->setChecked(inputSpec.value("default").toBool());
		inputWidget = check;
	} else if (type == "enum") {
		QComboBox *combo = new QComboBox(this);
		const QString defaultValue = inputSpec.value("default").toString();
		int defaultIndex = 0;
		const QVariantList options = inputSpec.value("options").toList();
		for (int i = 0; i < options.size(); ++i) {
			const QString option = options.at(i).toString();
			combo->addItem(option);
			if (option == defaultValue) {
				defaultIndex = i;
			}
		}
		combo->setCurrentIndex(defaultIndex);
		inputWidget = combo;
	} else if (type == "file") {
		QWidget *fileRow = new QWidget(this);
		QHBoxLayout *fileLayout = new QHBoxLayout(fileRow);
		fileLayout->setContentsMargins(0, 0, 0, 0);
		QLineEdit *lineEdit = new QLineEdit(inputSpec.value("default").toString(), fileRow);
		QPushButton *browseButton = new QPushButton("Browse...", fileRow);
		browseButton->setProperty("dsp_filter", inputSpec.value("filter"));
		fileLayout->addWidget(lineEdit);
		fileLayout->addWidget(browseButton);
		m_browseTargets.insert(browseButton, lineEdit);
		connect(browseButton, SIGNAL(clicked()), this, SLOT(onBrowseFileClicked()));
		inputWidget = fileRow;
		// The QLineEdit (not the wrapping row widget) is what
		// collectedInputs() reads back from -- record it directly.
		m_inputWidgets.insert(name, {lineEdit, type});
		m_form->addRow(label, fileRow);
		return;
	} else {
		// "string" and anything unrecognized default to a plain text field,
		// so a future input type added to the manifest schema degrades
		// gracefully instead of silently dropping the row.
		QLineEdit *lineEdit = new QLineEdit(inputSpec.value("default").toString(), this);
		inputWidget = lineEdit;
	}

	m_inputWidgets.insert(name, {inputWidget, type});
	m_form->addRow(label, inputWidget);
}

void DzPackageInputsDialog::onBrowseFileClicked() {
	QObject *button = sender();
	QLineEdit *target = m_browseTargets.value(button, nullptr);
	if (!target) {
		return;
	}

	const QString filter = button->property("dsp_filter").toString();
	const QString chosen = QFileDialog::getOpenFileName(this, "Choose File", target->text(), filter);
	if (!chosen.isEmpty()) {
		target->setText(chosen);
	}
}

QVariantMap DzPackageInputsDialog::collectedInputs() const {
	QVariantMap result;

	for (auto it = m_inputWidgets.constBegin(); it != m_inputWidgets.constEnd(); ++it) {
		const QString &name = it.key();
		const InputWidget &entry = it.value();

		if (entry.type == "int") {
			result[name] = qobject_cast<QSpinBox *>(entry.widget)->value();
		} else if (entry.type == "float") {
			result[name] = qobject_cast<QDoubleSpinBox *>(entry.widget)->value();
		} else if (entry.type == "bool") {
			result[name] = qobject_cast<QCheckBox *>(entry.widget)->isChecked();
		} else if (entry.type == "enum") {
			result[name] = qobject_cast<QComboBox *>(entry.widget)->currentText();
		} else {
			// "string" and "file" both end up as a QLineEdit.
			result[name] = qobject_cast<QLineEdit *>(entry.widget)->text();
		}
	}

	return result;
}

// Manually included -- CMAKE_AUTOMOC_MOC_OPTIONS -i (top-level CMakeLists.txt)
// is set project-wide, which suppresses moc's default self-include of this
// class's own header for every Q_OBJECT class, not just pluginmain.cpp's
// inline one it was added for. Same pattern PythonToolchainBootstrapper.cpp/
// PackageDependencyInstaller.cpp already use.
#include "moc_DzPackageInputsDialog.cpp"
