# Workflow Architecture

This document provides a visual overview of how the GitHub Actions workflows are structured and interact.

## Workflow Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                      TRIGGER WORKFLOWS                           │
└─────────────────────────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌──────────────────┐   ┌──────────────┐
│ release-      │   │ release-nightly  │   │ test-build   │
│ tagged.yml    │   │ .yml             │   │ .yml         │
│               │   │                  │   │              │
│ Trigger:      │   │ Trigger:         │   │ Trigger:     │
│ • Tags v*.*.*  │   │ • Scheduled      │   │ • Manual     │
│               │   │   (1 AM EST)     │   │              │
│               │   │ • Manual         │   │              │
└───────┬───────┘   └────────┬─────────┘   └──────┬───────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
        ┌────────────────────┼────────────────────┬────────────┐
        │                    │                    │            │
        ▼                    ▼                    ▼            ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────┐  ┌──────────────┐
│ build-       │   │ build-macos.yml  │   │ build-       │  │ ci.yml       │
│ windows.yml  │   │                  │   │ dazpy.yml    │  │              │
│              │   │ Called 4x:       │   │              │  │ Trigger:     │
│ Called 2x:   │   │ • Intel DS4      │   │ (Reusable)   │  │ • Push       │
│ • DS4        │   │ • Intel DS6      │   │              │  │ • PR         │
│ • DS6        │   │ • ARM64 DS4      │   │              │  │              │
│              │   │ • ARM64 DS6      │   │              │  │              │
└──────────────┘   └──────────────────┘   └──────────────┘  └──────────────┘
```

## Data Flow

### Tagged Release Flow

```
User pushes tag (v1.3.0)
         │
         ▼
   release-tagged.yml triggered
         │
         ├──► build-windows.yml (DS4) ─────┐
         │                                  │
         ├──► build-windows.yml (DS6) ─────┤
         │                                  │
         ├──► build-macos.yml (Intel DS4) ──┤
         │                                  │
         ├──► build-macos.yml (Intel DS6) ──┼──► Artifacts uploaded
         │                                  │    to GitHub
         ├──► build-macos.yml (ARM DS4) ────┤
         │                                  │
         ├──► build-macos.yml (ARM DS6) ────┤
         │                                  │
         └──► build-dazpy.yml ──────────────┘
                     │
                     ▼
         Download all artifacts
                     │
                     ▼
         Generate commit summary
                     │
                     ▼
         Create GitHub Release
                     │
                     ▼
         Attach all artifacts:
         • DazScriptServer-ds4-windows.dll
         • DazScriptServer-ds4-macos-Intel.dylib
         • DazScriptServer-ds4-macos-AppleSilicon.dylib
         • dsp_DazScriptServer-ds6-windows.dll
         • dsp_DazScriptServer-ds6-macos-Intel.dylib
         • dsp_DazScriptServer-ds6-macos-AppleSilicon.dylib
         • dazpy-*.whl
         • Source.zip (auto)
         • Source.tar.gz (auto)
```

### Nightly Release Flow

```
Scheduled trigger (1 AM EST daily)
         │
         ▼
   Check for new commits
         │
    ┌────┴────┐
    │         │
 No │         │ Yes
    │         │
    ▼         ▼
  Skip    Delete previous nightly
            │
            ▼
      Build all artifacts (parallel)
            │
            ▼
      Generate commit summary
            │
            ▼
      Create new nightly release
            │
            ▼
      Tag: nightly-<run_number>
      Marked as: Prerelease
```

## Build Workflow Details

### build-windows.yml

```
Input: sdk-version (4/6), configuration (Release/Debug)
   │
   ▼
Set SDK paths and DLL name:
 • DS4 ──► DazScriptServer.dll
 • DS6 ──► dsp_DazScriptServer.dll
   │
   ▼
Download DAZ SDK ──► Cache (version-specific) for next run
   │
   ▼
Install Qt6 via aqtinstall (DS6 only) ──► Cache for next run
   │
   ▼
Verify SDK structure
   │
   ▼
Configure CMake (DAZ_SDK_VERSION=4 or 6)
   │
   ▼
Build with MSBuild
   │
   ▼
Verify DLL exists
   │
   ▼
Upload artifact: DazScriptServer-windows-ds{version}-{config}
   │
   ▼
Output: artifact-name
```

### build-macos.yml

```
Input: architecture (x86_64/arm64), sdk-version (4/6), configuration
   │
   ▼
Select runner:
 • x86_64 ──► self-hosted macOS X64
 • arm64 ───► macos-14
   │
   ▼
Set SDK paths and dylib name:
 • DS4 ──► DazScriptServer.dylib
 • DS6 ──► dsp_DazScriptServer.dylib
   │
   ▼
Download DAZ SDK ──► Cache (version-specific) for next run
   │
   ▼
Install Qt6 via aqtinstall (DS6 only) ──► Cache for next run
   │
   ▼
Verify SDK structure
   │
   ▼
Configure CMake with:
 CMAKE_OSX_ARCHITECTURES={arch}, DAZ_SDK_VERSION={4|6}
   │
   ▼
Build with CMake
   │
   ▼
Verify dylib with lipo
   │
   ▼
Upload artifact: DazScriptServer-macos-{arch}-ds{version}-{config}
   │
   ▼
Output: artifact-name
```

### build-dazpy.yml

```
Setup Python 3.10
   │
   ▼
Install build dependencies
   │
   ▼
Build wheel with python-build
   │
   ▼
Verify wheel exists
   │
   ▼
Upload artifact: dazpy-wheel
   │
   ▼
Output: artifact-name
```

## Cache Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions Cache                      │
└─────────────────────────────────────────────────────────────┘
           │                                │
    SDK Caches (4 keys)              Qt6 Caches (2 keys, DS6 only)
           │                                │
    ┌──────┼──────┐               ┌─────────┴──────────┐
    │      │      │               │                    │
    ▼      ▼      ▼               ▼                    ▼
 Win-DS4 Win-DS6 Mac-DS4 Mac-DS6  Win Qt6           Mac Qt6
 private private private private  6.10.3-            6.10.3-
 -v1     -v1     -v1     -v1      msvc2022_64        clang_64
                                  -qt5compat-v1      -qt5compat-v1

All caches TTL: 7 days
```

## Parallel Execution

### Tagged Release Timeline

```
Time →

0:00  ┌─ build-windows (DS4) ──────────┐
      │                                 │
      ├─ build-windows (DS6) ──────────┤
      │                                 │
      ├─ build-macos Intel (DS4) ───────┤
      │                                 │
      ├─ build-macos Intel (DS6) ───────┤  ← All 7 jobs run in parallel
      │                                 │
      ├─ build-macos ARM (DS4) ─────────┤
      │                                 │
      ├─ build-macos ARM (DS6) ─────────┤
      │                                 │
      └─ build-dazpy ──────────────────┘

20:00                                  All builds complete
                                            │
                                            ▼
                                       create-release job
                                            │
                                            ▼
                                       Download artifacts
                                            │
                                            ▼
                                       Generate notes
                                            │
                                            ▼
                                       Create release

20:00                                  Release published
```

## Conditional Logic

### Nightly Workflow Decision Tree

```
                    Scheduled trigger
                           │
                           ▼
              ┌───────────────────────┐
              │ Get previous nightly  │
              │ tag (if exists)       │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │ Get commits since     │
              │ previous nightly or   │
              │ last tagged release   │
              └───────────┬───────────┘
                          │
                    ┌─────┴─────┐
                    │           │
            No commits      Has commits
                    │           │
                    ▼           ▼
               ┌────────┐  ┌─────────────────┐
               │ Skip   │  │ Delete previous │
               │ build  │  │ nightly         │
               └────────┘  └────────┬────────┘
                                    │
                                    ▼
                          ┌──────────────────┐
                          │ Build artifacts  │
                          └────────┬─────────┘
                                   │
                                   ▼
                          ┌──────────────────┐
                          │ Create nightly   │
                          │ release          │
                          └──────────────────┘
```

## Artifact Lifecycle

```
┌──────────────────────────────────────────────────────────────┐
│                      Build Artifacts                          │
│                                                               │
│  Created during workflow runs                                │
│  Stored in GitHub Actions artifact storage                   │
│  TTL: 90 days                                                │
│  Access: Download from workflow run page                     │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                     Release Assets                            │
│                                                               │
│  Attached to GitHub Releases                                 │
│  TTL: Permanent                                              │
│  Access: Release page, API, gh CLI                           │
└──────────────────────────────────────────────────────────────┘
```

## Workflow Dependencies

```
┌─────────────────┐
│ release-tagged  │───┐
└─────────────────┘   │
                      │
┌─────────────────┐   │    ┌──────────────┐
│ release-nightly │───┼────│ build-       │
└─────────────────┘   │    │ windows      │
                      │    └──────────────┘
┌─────────────────┐   │
│ test-build      │───┤    ┌──────────────┐
└─────────────────┘   │    │ build-macos  │
                      ├────│              │
                      │    │ (3 variants) │
                      │    └──────────────┘
                      │
                      │    ┌──────────────┐
                      └────│ build-dazpy  │
                           └──────────────┘

Legend:
───┐ = "calls/uses"
   │
   └─ (reusable workflow)
```

## Release Asset Naming

### Tagged Release (v1.3.0)

```
GitHub Release: v1.3.0
├── DazScriptServer-ds4-windows.dll          ← DAZ Studio 4.5+
├── DazScriptServer-ds4-macos-Intel.dylib
├── DazScriptServer-ds4-macos-AppleSilicon.dylib
├── dsp_DazScriptServer-ds6-windows.dll      ← DAZ Studio 6.25+
├── dsp_DazScriptServer-ds6-macos-Intel.dylib
├── dsp_DazScriptServer-ds6-macos-AppleSilicon.dylib
├── dazpy-2.6.0-py3-none-any.whl
├── Source code (zip)           ← Auto-generated
└── Source code (tar.gz)        ← Auto-generated
```

### Nightly Release (nightly-123)

```
GitHub Release: nightly-123
├── DazScriptServer-ds4-windows.dll
├── DazScriptServer-ds4-macos-Intel.dylib
├── DazScriptServer-ds4-macos-AppleSilicon.dylib
├── dsp_DazScriptServer-ds6-windows.dll
├── dsp_DazScriptServer-ds6-macos-Intel.dylib
├── dsp_DazScriptServer-ds6-macos-AppleSilicon.dylib
├── dazpy-2.6.0-py3-none-any.whl
├── Source code (zip)           ← Auto-generated
└── Source code (tar.gz)        ← Auto-generated

Metadata:
• Marked as: Prerelease
• Tag format: nightly-<run_number>
• Overwrites: Previous nightly release deleted
```

## Permission Model

```
┌─────────────────────────────────────────────────────┐
│              Repository Permissions                  │
│                                                      │
│  Settings → Actions → General → Workflow permissions │
└──────────────────────┬──────────────────────────────┘
                       │
            ┌──────────┴──────────┐
            │                     │
            ▼                     ▼
   ┌────────────────┐    ┌────────────────┐
   │ contents:      │    │ actions:       │
   │ write          │    │ read           │
   │                │    │                │
   │ Required for:  │    │ Required for:  │
   │ • Releases     │    │ • Artifacts    │
   │ • Tags         │    │   (implicit)   │
   └────────────────┘    └────────────────┘
```

## Error Handling

```
                Build Workflow
                      │
              ┌───────┴───────┐
              │               │
         Success          Failure
              │               │
              ▼               ▼
    ┌─────────────────┐  ┌──────────────┐
    │ Upload artifact │  │ Workflow     │
    │                 │  │ fails        │
    └────────┬────────┘  │              │
             │           │ Release job  │
             │           │ doesn't run  │
             │           │              │
             │           │ Artifacts    │
             │           │ not created  │
             │           └──────────────┘
             ▼
    Release workflow
    (needs: all builds)
             │
      ┌──────┴──────┐
      │             │
 All success    Any failure
      │             │
      ▼             ▼
 Create         Skip release
 release        creation
```

## Scaling Considerations

### Current Capacity

```
Builds per release:     7 jobs (6 plugin + 1 dazpy, all parallel)
Time per release:       ~20-25 minutes
Nightly frequency:      Daily (1 AM EST)
Tagged releases:        On-demand

Annual estimates:
• Nightly builds:       365 builds/year
• Tagged releases:      ~12-24 builds/year (estimate)
• Total runs:           ~377-389/year
• Total minutes (metered): ~9,425-12,463/year
  (macOS Intel jobs use self-hosted runner — no metered cost)
```

## Summary

The architecture uses a modular, composable design:

1. **Reusable workflows** for each build type
2. **Trigger workflows** that orchestrate releases
3. **Parallel execution** for efficiency
4. **Smart caching** to reduce build times
5. **Conditional logic** to avoid unnecessary builds
6. **Proper error handling** to fail fast

This design allows for:
- Easy maintenance (changes in one place)
- Cost optimization (parallel + cached)
- Flexibility (manual testing, multiple triggers)
- Scalability (easy to add new platforms/SDKs)
