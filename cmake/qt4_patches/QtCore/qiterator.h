/****************************************************************************
**
** Patched for modern macOS/clang compatibility.
**
** Original copyright (C) 2012 Nokia Corporation and/or its subsidiary(-ies).
** Licensed under GNU LGPL v2.1 — see the original file for the full license.
**
** Change from original: the bare namespace std { struct ...; } forward
** declarations at the top of the file have been replaced with
** #include <iterator>.  On modern libc++ (Xcode 12+) those forward
** declarations create an ambiguous-lookup error because the same names are
** already exported into std via the std::__1 inline namespace.  Using the
** real <iterator> header instead avoids the duplicate declarations entirely.
**
****************************************************************************/

#ifndef QITERATOR_H
#define QITERATOR_H

#include <QtCore/qglobal.h>
#include <iterator>

QT_BEGIN_HEADER

QT_BEGIN_NAMESPACE

QT_MODULE(Core)

#define Q_DECLARE_SEQUENTIAL_ITERATOR(C) \
\
template <class T> \
class Q##C##Iterator \
{ \
    typedef typename Q##C<T>::const_iterator const_iterator; \
    Q##C<T> c; \
    const_iterator i; \
public: \
    inline Q##C##Iterator(const Q##C<T> &container) \
        : c(container), i(c.constBegin()) {} \
    inline Q##C##Iterator &operator=(const Q##C<T> &container) \
    { c = container; i = c.constBegin(); return *this; } \
    inline void toFront() { i = c.constBegin(); } \
    inline void toBack() { i = c.constEnd(); } \
    inline bool hasNext() const { return i != c.constEnd(); } \
    inline const T &next() { return *i++; } \
    inline const T &peekNext() const { return *i; } \
    inline bool hasPrevious() const { return i != c.constBegin(); } \
    inline const T &previous() { return *--i; } \
    inline const T &peekPrevious() const { const_iterator p = i; return *--p; } \
    inline bool findNext(const T &t) \
    { while (i != c.constEnd()) if (*i++ == t) return true; return false; } \
    inline bool findPrevious(const T &t) \
    { while (i != c.constBegin()) if (*(--i) == t) return true; \
      return false;  } \
};

#define Q_DECLARE_MUTABLE_SEQUENTIAL_ITERATOR(C) \
\
template <class T> \
class QMutable##C##Iterator \
{ \
    typedef typename Q##C<T>::iterator iterator; \
    typedef typename Q##C<T>::const_iterator const_iterator; \
    Q##C<T> *c; \
    iterator i, n; \
    inline bool item_exists() const { return const_iterator(n) != c->constEnd(); } \
public: \
    inline QMutable##C##Iterator(Q##C<T> &container) \
        : c(&container) \
    { c->setSharable(false); i = c->begin(); n = c->end(); } \
    inline ~QMutable##C##Iterator() \
    { c->setSharable(true); } \
    inline QMutable##C##Iterator &operator=(Q##C<T> &container) \
    { c->setSharable(true); c = &container; c->setSharable(false); \
      i = c->begin(); n = c->end(); return *this; } \
    inline void toFront() { i = c->begin(); n = c->end(); } \
    inline void toBack() { i = c->end(); n = i; } \
    inline bool hasNext() const { return c->constEnd() != const_iterator(i); } \
    inline T &next() { n = i++; return *n; } \
    inline T &peekNext() const { return *i; } \
    inline bool hasPrevious() const { return c->constBegin() != const_iterator(i); } \
    inline T &previous() { n = --i; return *n; } \
    inline T &peekPrevious() const { iterator p = i; return --p; } \
    inline void remove() \
    { if (c->constEnd() != const_iterator(n)) { i = c->erase(n); n = c->end(); } } \
    inline void setValue(const T &t) const { if (c->constEnd() != const_iterator(n)) *n = t; } \
    inline T &value() { Q_ASSERT(item_exists()); return *n; } \
    inline const T &value() const { Q_ASSERT(item_exists()); return *n; } \
    inline void insert(const T &t) { n = i = c->insert(i, t); ++i; } \
    inline bool findNext(const T &t) \
    { while (c->constEnd() != const_iterator(n = i)) if (*i++ == t) return true; return false; } \
    inline bool findPrevious(const T &t) \
    { while (c->constBegin() != const_iterator(i)) if (*(n = --i) == t) return true; \
      n = c->end(); return false;  } \
};

#define Q_DECLARE_ASSOCIATIVE_ITERATOR(C) \
\
template <class Key, class T> \
class Q##C##Iterator \
{ \
    typedef typename Q##C<Key,T>::const_iterator const_iterator; \
    typedef const_iterator Item; \
    Q##C<Key,T> c; \
    const_iterator i, n; \
    inline bool item_exists() const { return n != c.constEnd(); } \
public: \
    inline Q##C##Iterator(const Q##C<Key,T> &container) \
        : c(container), i(c.constBegin()), n(c.constEnd()) {} \
    inline Q##C##Iterator &operator=(const Q##C<Key,T> &container) \
    { c = container; i = c.constBegin(); n = c.constEnd(); return *this; } \
    inline void toFront() { i = c.constBegin(); n = c.constEnd(); } \
    inline void toBack() { i = c.constEnd(); n = c.constEnd(); } \
    inline bool hasNext() const { return i != c.constEnd(); } \
    inline Item next() { n = i++; return n; } \
    inline Item peekNext() const { return i; } \
    inline bool hasPrevious() const { return i != c.constBegin(); } \
    inline Item previous() { n = --i; return n; } \
    inline Item peekPrevious() const { const_iterator p = i; return --p; } \
    inline const T &value() const { Q_ASSERT(item_exists()); return *n; } \
    inline const Key &key() const { Q_ASSERT(item_exists()); return n.key(); } \
    inline bool findNext(const T &t) \
    { while ((n = i) != c.constEnd()) if (*i++ == t) return true; return false; } \
    inline bool findPrevious(const T &t) \
    { while (i != c.constBegin()) if (*(n = --i) == t) return true; \
      n = c.constEnd(); return false; } \
};

#define Q_DECLARE_MUTABLE_ASSOCIATIVE_ITERATOR(C) \
\
template <class Key, class T> \
class QMutable##C##Iterator \
{ \
    typedef typename Q##C<Key,T>::iterator iterator; \
    typedef typename Q##C<Key,T>::const_iterator const_iterator; \
    typedef iterator Item; \
    Q##C<Key,T> *c; \
    iterator i, n; \
    inline bool item_exists() const { return const_iterator(n) != c->constEnd(); } \
public: \
    inline QMutable##C##Iterator(Q##C<Key,T> &container) \
        : c(&container) \
    { c->setSharable(false); i = c->begin(); n = c->end(); } \
    inline ~QMutable##C##Iterator() \
    { c->setSharable(true); } \
    inline QMutable##C##Iterator &operator=(Q##C<Key,T> &container) \
    { c->setSharable(true); c = &container; c->setSharable(false); i = c->begin(); n = c->end(); return *this; } \
    inline void toFront() { i = c->begin(); n = c->end(); } \
    inline void toBack() { i = c->end(); n = c->end(); } \
    inline bool hasNext() const { return const_iterator(i) != c->constEnd(); } \
    inline Item next() { n = i++; return n; } \
    inline Item peekNext() const { return i; } \
    inline bool hasPrevious() const { return const_iterator(i) != c->constBegin(); } \
    inline Item previous() { n = --i; return n; } \
    inline Item peekPrevious() const { iterator p = i; return --p; } \
    inline void remove() \
    { if (const_iterator(n) != c->constEnd()) { i = c->erase(n); n = c->end(); } } \
    inline void setValue(const T &t) { if (const_iterator(n) != c->constEnd()) *n = t; } \
    inline T &value() { Q_ASSERT(item_exists()); return *n; } \
    inline const T &value() const { Q_ASSERT(item_exists()); return *n; } \
    inline const Key &key() const { Q_ASSERT(item_exists()); return n.key(); } \
    inline bool findNext(const T &t) \
    { while (const_iterator(n = i) != c->constEnd()) if (*i++ == t) return true; return false; } \
    inline bool findPrevious(const T &t) \
    { while (const_iterator(i) != c->constBegin()) if (*(n = --i) == t) return true; \
      n = c->end(); return false; } \
};

QT_END_NAMESPACE

QT_END_HEADER

#endif // QITERATOR_H
