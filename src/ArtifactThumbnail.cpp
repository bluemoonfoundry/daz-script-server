#include "ArtifactThumbnail.h"

#include <QtCore/qbuffer.h>
#include <QtCore/qsize.h>
#include <QtGui/qcolor.h>
#include <QtGui/qimage.h>
#include <QtGui/qimagereader.h>
#include <QtGui/qpainter.h>

#include <cstdlib>
#include <string>

namespace ArtifactThumbnail {

const char* contentType(Format f) { return f == FORMAT_JPEG ? "image/jpeg" : "image/png"; }
const char* extension(Format f)   { return f == FORMAT_JPEG ? "jpg" : "png"; }

bool parseParams(const std::string& thumbnail, const std::string& format, bool hasFormat,
                 int* outPx, Format* outFormat, std::string* error)
{
    // Digits only: no sign, spaces or suffix, and short enough not to overflow.
    bool digits = !thumbnail.empty() && thumbnail.size() <= 5;
    for (size_t i = 0; digits && i < thumbnail.size(); ++i)
        digits = thumbnail[i] >= '0' && thumbnail[i] <= '9';
    const int px = digits ? std::atoi(thumbnail.c_str()) : 0;
    if (px < kMinPx || px > kMaxPx) {
        *error = "thumbnail must be an integer from " + std::to_string(kMinPx)
               + " to " + std::to_string(kMaxPx) + " (pixels, longest edge)";
        return false;
    }

    Format f = FORMAT_PNG;
    if (hasFormat) {
        if (format == "png") {
            f = FORMAT_PNG;
        } else if (format == "jpeg" || format == "jpg") {
            f = FORMAT_JPEG;
        } else {
            *error = "format must be png or jpeg";
            return false;
        }
    }
    *outPx = px;
    *outFormat = f;
    return true;
}

void release(Job* job)
{
    if (job && !job->refs.deref())
        delete job;
}

// Fit (w, h) inside a maxPx box, keeping the aspect ratio. Never upscales.
static QSize fitWithin(const QSize& src, int maxPx)
{
    if (src.width() <= maxPx && src.height() <= maxPx) return src;
    QSize out = src;
    out.scale(maxPx, maxPx, Qt::KeepAspectRatio);
    if (out.width() < 1)  out.setWidth(1);
    if (out.height() < 1) out.setHeight(1);
    return out;
}

static void decode(Job* job)
{
    QBuffer in(&job->source);
    if (!in.open(QIODevice::ReadOnly)) {
        job->error = QString("could not read the artifact bytes");
        return;
    }
    QImageReader reader(&in);
    if (!reader.canRead()) {
        job->error = QString("not an image format this DAZ Studio's Qt can decode");
        return;
    }

    const QSize srcSize = reader.size();
    if (srcSize.isValid()) {
        if ((qint64)srcSize.width() * (qint64)srcSize.height() > kMaxSourcePixels) {
            job->error = QString("image is %1x%2; thumbnails are limited to %3 megapixels")
                .arg(srcSize.width()).arg(srcSize.height()).arg(kMaxSourcePixels / 1000000);
            return;
        }
        // JPEG decodes straight to the smaller size; other formats are read
        // in full and scaled by QImageReader.
        reader.setScaledSize(fitWithin(srcSize, job->maxPx));
    }

    QImage img = reader.read();
    if (img.isNull()) {
        job->error = QString("decode failed: ") + reader.errorString();
        return;
    }
    if (!srcSize.isValid()) {
        // Handler couldn't report the size up front: scale after reading.
        const QSize target = fitWithin(img.size(), job->maxPx);
        if (target != img.size())
            img = img.scaled(target, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    }

    QBuffer out(&job->image);
    out.open(QIODevice::WriteOnly);
    bool saved = false;
    if (job->format == FORMAT_JPEG) {
        // JPEG has no alpha: flatten onto white rather than letting
        // transparent pixels turn black.
        QImage flat(img.size(), QImage::Format_RGB32);
        flat.fill(QColor(Qt::white).rgb());
        {
            QPainter painter(&flat);
            painter.drawImage(0, 0, img);
        }
        saved = flat.save(&out, "JPEG", 85);
    } else {
        saved = img.save(&out, "PNG");
    }
    out.close();
    if (!saved || job->image.isEmpty()) {
        job->image.clear();
        job->error = QString("encoding the thumbnail failed");
        return;
    }
    job->ok = true;
}

void run(Job* job)
{
    if (!job) return;
    if (job->abandoned.fetchAndAddOrdered(0) == 0)
        decode(job);
    job->done.release();
    release(job);
}

QStringList readableExtensions()
{
    QStringList exts;
    const QList<QByteArray> formats = QImageReader::supportedImageFormats();
    for (int i = 0; i < formats.size(); ++i) {
        const QString f = QString::fromLatin1(formats[i].constData()).toLower();
        if (!f.isEmpty() && !exts.contains(f)) exts.append(f);
    }
    // Plugins report "jpeg"/"tiff"; files usually say ".jpg"/".tif".
    if (exts.contains("jpeg") && !exts.contains("jpg")) exts.append("jpg");
    if (exts.contains("tiff") && !exts.contains("tif")) exts.append("tif");
    return exts;
}

bool extensionIn(const QString& path, const QStringList& exts)
{
    const int dot = path.lastIndexOf(QChar('.'));
    const int sep = qMax(path.lastIndexOf(QChar('/')), path.lastIndexOf(QChar('\\')));
    if (dot < 0 || dot < sep) return false;
    return exts.contains(path.mid(dot + 1).toLower());
}

// ─── Cache ───────────────────────────────────────────────────────────────────

Cache::Cache(int capacity) : m_capacity(capacity > 0 ? capacity : 1) {}

QString Cache::key(const QString& path, qint64 size, qint64 mtime, int px, Format f)
{
    return QString("%1|%2|%3|%4|%5").arg(size).arg(mtime).arg(px)
        .arg(QString::fromLatin1(extension(f))).arg(path);
}

bool Cache::get(const QString& key, QByteArray* out)
{
    QMutexLocker lock(&m_mutex);
    QMap<QString, QByteArray>::const_iterator it = m_entries.constFind(key);
    if (it == m_entries.constEnd()) return false;
    *out = it.value();
    m_order.removeAll(key);
    m_order.append(key);
    return true;
}

void Cache::put(const QString& key, const QByteArray& image)
{
    QMutexLocker lock(&m_mutex);
    if (!m_entries.contains(key)) {
        while (m_order.size() >= m_capacity) {
            m_entries.remove(m_order.first());
            m_order.removeFirst();
        }
        m_order.append(key);
    }
    m_entries.insert(key, image);
}

void Cache::clear()
{
    QMutexLocker lock(&m_mutex);
    m_entries.clear();
    m_order.clear();
}

} // namespace ArtifactThumbnail
