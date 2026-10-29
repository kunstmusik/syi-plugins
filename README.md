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
Load a module with Csound's `--opcode-lib` option, or install it below.

## Install

With Unix Makefiles (CMake's usual default on macOS and Linux):

```sh
make -C build install
```

This builds and installs all opcode libraries into your Csound user plugin
directory, without `sudo`. The generator-independent equivalent is
`cmake --build build --target install`; for a multi-configuration generator,
add `--config Release`. To install an already built tree, use
`cmake --install build` (with `--config Release` if needed).

Defaults follow Csound's loader, using the API version and sample precision
from the selected SDK headers. For Csound 7.0:

| Platform | Double samples | Float samples |
| --- | --- | --- |
| macOS | `~/Library/csound/7.0/plugins64` | `~/Library/csound/7.0/plugins` |
| Linux | `~/.local/lib/csound/7.0/plugins64` | `~/.local/lib/csound/7.0/plugins` |
| Windows | `%LOCALAPPDATA%/csound/7.0/plugins64` | `%LOCALAPPDATA%/csound/7.0/plugin` |

The Windows float directory is singular `plugin` in the current Csound source.
These paths were checked against `csound/CMakeLists.txt` and
`csound/Top/csmodule.c`. The `plugins/7.x` build uses the same macOS/Windows
double defaults and `install(TARGETS ...)`; its Linux default is a system
directory instead of the user directory used here.

Override the destination at configure time if your Csound build uses a custom
path:

```sh
cmake -S . -B build -DPLUGIN_INSTALL_DIR=/absolute/path/to/plugins
make -C build install
```

The absolute destination is cached when configured; `CMAKE_INSTALL_PREFIX`
does not relocate it. Csound normally discovers installed user plugins
automatically. Setting `CS_USER_PLUGINDIR` replaces that user search path and
can contain multiple directories (`:` on Unix, `;` on Windows), so the build
does not use it as an install destination. Set `PLUGIN_INSTALL_DIR` to one of
those directories if you use that override. Restart Blue or other running
Csound hosts after updating a plugin.

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
`BUILD_TESTING` are shared by the root build. Add `install(TARGETS <target>
LIBRARY DESTINATION "${PLUGIN_INSTALL_DIR}" RUNTIME DESTINATION
"${PLUGIN_INSTALL_DIR}")` for each library so it participates in `make install`.
