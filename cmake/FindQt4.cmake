# cmake/FindQt4.cmake
#
# macOS-only replacement for CMake's system FindQt4.
# The DAZ SDK's qmake is an i386 binary that cannot run on macOS 10.15+, so the
# system FindQt4 always fails there.  This file skips qmake entirely and
# constructs the same variables and imported targets that the system module
# would produce, pointing at the x86_64 frameworks in the SDK.
#
# On Windows, this file is never added to CMAKE_MODULE_PATH (see the guard in
# the parent CMakeLists.txt), so the system FindQt4 is used unchanged.

if(NOT APPLE)
    message(FATAL_ERROR "cmake/FindQt4.cmake is macOS-only; should not be reached on other platforms")
endif()

# ── Locate SDK paths ─────────────────────────────────────────────────────────

if(NOT DAZ_SDK_DIR)
    message(FATAL_ERROR "FindQt4 (macOS): DAZ_SDK_DIR must be set before find_package(Qt4)")
endif()

# DZ_MIXED_PLATFORM is set by the parent CMakeLists before find_package is called.
if(NOT DZ_MIXED_PLATFORM)
    set(DZ_MIXED_PLATFORM "Mac64")
endif()

set(_QT_FWDIR  "${DAZ_SDK_DIR}/lib/${DZ_MIXED_PLATFORM}")
set(_QT_BINDIR "${DAZ_SDK_DIR}/bin/${DZ_MIXED_PLATFORM}")
set(_QT_INCDIR "${DAZ_SDK_DIR}/include")

# ── Version ──────────────────────────────────────────────────────────────────

set(QT_VERSION_MAJOR 4)
set(QT_VERSION_MINOR 8)
set(QT_VERSION_PATCH 7)
set(QT_VERSION       "4.8.7")

# ── Standard "found" variables ───────────────────────────────────────────────

set(QT_FOUND        TRUE)
set(QT4_FOUND       TRUE)
set(Qt4_FOUND       TRUE)
set(QT_INCLUDE_DIR  "${_QT_INCDIR}")
set(QT_LIBRARY_DIR  "${_QT_FWDIR}")
set(QT_BINARY_DIR   "${_QT_BINDIR}")

# ── moc executable (CACHE so AUTOMOC picks it up) ────────────────────────────

set(QT_MOC_EXECUTABLE "${_QT_BINDIR}/moc" CACHE FILEPATH "Qt4 moc executable" FORCE)
set(QT4_MOC_EXECUTABLE "${_QT_BINDIR}/moc" CACHE FILEPATH "Qt4 moc executable" FORCE)

if(NOT TARGET Qt4::moc)
    add_executable(Qt4::moc IMPORTED)
    set_property(TARGET Qt4::moc PROPERTY IMPORTED_LOCATION "${_QT_BINDIR}/moc")
endif()

# ── Qt4 module targets ────────────────────────────────────────────────────────
# find_library resolves <name>.framework to a path CMake treats as a framework
# link, generating the correct -framework <name> -F <dir> flags automatically.

foreach(_mod QtCore QtGui QtScript QtNetwork)
    find_library(_QT_FW_${_mod} ${_mod} PATHS "${_QT_FWDIR}" NO_DEFAULT_PATH)
    if(NOT _QT_FW_${_mod})
        message(FATAL_ERROR "FindQt4 (macOS): framework ${_mod} not found in ${_QT_FWDIR}")
    endif()

    if(NOT TARGET Qt4::${_mod})
        add_library(Qt4::${_mod} INTERFACE IMPORTED)
        set_property(TARGET Qt4::${_mod} PROPERTY
            INTERFACE_LINK_LIBRARIES "${_QT_FW_${_mod}}")
        # Headers live in the flat include tree, not inside the framework bundle.
        set_property(TARGET Qt4::${_mod} PROPERTY
            INTERFACE_INCLUDE_DIRECTORIES
                "${_QT_INCDIR}"
                "${_QT_INCDIR}/${_mod}")
    endif()
endforeach()

# AUTOMOC requires QT4_FOUND and Qt4::moc to detect the Qt version.
set_property(TARGET Qt4::QtCore PROPERTY QT4_MOC_EXECUTABLE "${_QT_BINDIR}/moc")
