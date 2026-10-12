# syi-plugins

Native Csound opcode plugin libraries. Each library has its own directory,
README, CMake target, source, examples, and tests.

| Library | Description | Csound |
| --- | --- | --- |
| [juno60vcf](juno60vcf/README.md) | Juno-60 four-pole lowpass filter with nonlinear resonance feedback | 7 |

## Build

Requires CMake 3.18 or newer, a C compiler, Csound 7 SDK headers matching the
host's version and sample precision, pkg-config, and libsamplerate development
files. Tests also require Python 3 and the Csound 7 executable; they use only
Python's standard library.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
ctest --test-dir build --output-on-failure
```

Pass `-DCSOUND_INCLUDE_DIR=/path/to/csound/headers` for an SDK outside standard
locations. macOS framework headers are discovered automatically. Pass
`-DBUILD_TESTING=OFF` to build without Python or the Csound executable.

Modules are written to `build/<library>/`: `.dylib` on macOS, `.so` on Linux,
or `.dll` on Windows. Multi-configuration generators add the configuration
directory; use `--config Release` when building and `-C Release` with CTest.
Load a module with Csound's `--opcode-lib` option or copy it to the appropriate
Csound opcode directory. This build does not install plugins globally.

## Layout

```text
CMakeLists.txt
README.md
juno60vcf/
  CMakeLists.txt
  README.md
  src/
  examples/
  tests/
```

To add a library, create a sibling directory with its own `README.md`,
`CMakeLists.txt`, and `src/`, plus examples and tests as needed. Register it
with `add_subdirectory(<library>)` in the top-level CMake file. Keep dependencies
and target settings in the library's CMake file; `CSOUND_INCLUDE_DIR` and
`BUILD_TESTING` are shared by the root build.
