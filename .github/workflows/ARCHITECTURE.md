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
│              │   │ Called 3x:       │   │              │  │ Trigger:     │
│ (Reusable)   │   │ • Intel x86_64   │   │ (Reusable)   │  │ • Push       │
│              │   │ • ARM64          │   │              │  │ • PR         │
│              │   │ • Universal      │   │              │  │              │
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
         ├──► build-windows.yml ──────┐
         │                            │
         ├──► build-macos.yml (Intel) ┤
         │                            │
         ├──► build-macos.yml (ARM)   ├──► Artifacts uploaded
         │                            │    to GitHub
         ├──► build-macos.yml (Univ.) │
         │                            │
         └──► build-dazpy.yml ────────┘
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
         • DazScriptServer-windows.dll
         • DazScriptServer-macos-Intel.dylib
         • DazScriptServer-macos-AppleSilicon.dylib
         • DazScriptServer-macos-Universal.dylib
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
Input: configuration (Release/Debug)
   │
   ▼
Download DAZ SDK ──► Cache for next run
   │
   ▼
Verify SDK structure
   │
   ▼
Configure CMake
   │
   ▼
Build with MSBuild
   │
   ▼
Verify DLL exists
   │
   ▼
Upload artifact: DazScriptServer-windows-{config}
   │
   ▼
Output: artifact-name
```

### build-macos.yml

```
Input: architecture (x86_64/arm64/universal), configuration
   │
   ▼
Select runner:
 • x86_64 ──► macos-13
 • arm64 ───► macos-14
 • universal ► macos-14
   │
   ▼
Download DAZ SDK ──► Cache for next run
   │
   ▼
Verify SDK structure
   │
   ▼
Configure CMake with:
 CMAKE_OSX_ARCHITECTURES={arch}
   │
   ▼
Build with CMake
   │
   ▼
Verify dylib with lipo
   │
   ▼
Upload artifact: DazScriptServer-macos-{arch}-{config}
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
┌─────────────────────────────────────────────────┐
│              GitHub Actions Cache                │
└─────────────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼
┌──────────────────┐   ┌──────────────────┐
│ Windows Cache    │   │ macOS Cache      │
│                  │   │                  │
│ Key:             │   │ Key:             │
│ daz-sdk-4.5-     │   │ daz-sdk-4.5-     │
│ windows-v1       │   │ macos-v1         │
│                  │   │                  │
│ Contents:        │   │ Contents:        │
│ DAZStudio4.5+    │   │ DAZStudio4.5+    │
│ SDK/             │   │ SDK/             │
│ ├─ include/      │   │ ├─ include/      │
│ ├─ lib/          │   │ ├─ lib/          │
│ └─ bin/          │   │ └─ bin/          │
│                  │   │                  │
│ TTL: 7 days      │   │ TTL: 7 days      │
└──────────────────┘   └──────────────────┘
```

## Parallel Execution

### Tagged Release Timeline

```
Time →

0:00  ┌─ build-windows ────────────────┐
      │                                 │
      ├─ build-macos (Intel) ──────────┤
      │                                 │
      ├─ build-macos (ARM) ────────────┤  ← All builds run in parallel
      │                                 │
      ├─ build-macos (Universal) ──────┤
      │                                 │
      └─ build-dazpy ──────────────────┘

15:00                                  All builds complete
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
├── DazScriptServer-windows.dll
├── DazScriptServer-macos-Intel.dylib
├── DazScriptServer-macos-AppleSilicon.dylib
├── DazScriptServer-macos-Universal.dylib
├── dazpy-2.6.0-py3-none-any.whl
├── Source code (zip)           ← Auto-generated
└── Source code (tar.gz)        ← Auto-generated
```

### Nightly Release (nightly-123)

```
GitHub Release: nightly-123
├── DazScriptServer-windows.dll
├── DazScriptServer-macos-Intel.dylib
├── DazScriptServer-macos-AppleSilicon.dylib
├── DazScriptServer-macos-Universal.dylib
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
Builds per release:     5 jobs (parallel)
Time per release:       ~15-20 minutes
Nightly frequency:      Daily (1 AM EST)
Tagged releases:        On-demand

Annual estimates:
• Nightly builds:       365 builds/year
• Tagged releases:      ~12-24 builds/year (estimate)
• Total runs:           ~377-389/year
• Total minutes:        ~5,655-7,780/year
```

### Future Scaling

```
If SDK 6 is added:

Builds per release:     10 jobs (2× SDK versions)
Time per release:       ~20-25 minutes
Cache size:             2× (separate SDK caches)

Annual minutes:         ~11,310-15,560/year
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
