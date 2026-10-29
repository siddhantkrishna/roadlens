# Third-party notices and source locations

Original ROADLENS work is AGPL-3.0-only; see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Other components retain their own terms. The source repository includes no model
weights, virtual environment, native dependency binaries or generated app.

## Model and public media

- **YOLOv8n ONNX:** upstream Ultralytics AGPL-3.0 / commercial terms. The separate
  download is pinned by revision and SHA-256. Its export provenance remains a
  public-binary release gate; see [LICENSING.md](docs/LICENSING.md).
- **Ultralytics bus photograph:** original bytes from the upstream assets
  directory; retained under the upstream repository's AGPL terms.
- **Intel traffic clip:** frames 94-105 of `sample-videos/car-detection.mp4`,
  re-encoded as Motion JPEG at 12 FPS. CC BY 4.0; attribution: Intel sample videos
  contributors. See [assets/INTEL-LICENSE.txt](assets/INTEL-LICENSE.txt).
- **Screenshots:** ROADLENS UI over that Intel fixture. Original UI is
  AGPL-3.0-only; underlying footage retains CC BY 4.0 attribution.

Exact media sources/modifications and hashes are in [assets/README.md](assets/README.md)
and [docs/public-assets.json](docs/public-assets.json).

## Runtime components

| Component | Principal license / source |
| --- | --- |
| Python | [PSF license and bundled notices](https://docs.python.org/3/license.html) |
| Qt / PySide6 / Shiboken | [LGPLv3 / GPLv3 / commercial](https://doc.qt.io/qtforpython-6/licenses.html) |
| NumPy | [BSD-3-Clause and bundled library notices](https://numpy.org/doc/stable/license.html) |
| OpenCV | [Apache-2.0; wheel may include separately licensed codecs/libraries](https://github.com/opencv/opencv/blob/4.x/LICENSE) |
| Supervision / ByteTrack integration | [MIT](https://github.com/roboflow/supervision/blob/0.25.1/LICENSE.md) |
| SciPy | [BSD-3-Clause and bundled library notices](https://github.com/scipy/scipy/blob/main/LICENSE.txt) |
| Matplotlib | [Matplotlib license and bundled notices](https://matplotlib.org/stable/project/license.html) |
| Requests | [Apache-2.0](https://github.com/psf/requests/blob/main/LICENSE) |
| PyInstaller bootloader | [GPL-2.0-or-later with its bootloader exception](https://pyinstaller.org/en/stable/license.html) |

This table summarizes principal licenses, not every bundled native component.
The Intel lock records exact tested versions. Build/development/security tools
are not part of normal inference; their installed distributions retain their own
notices. Check the exact dependency artifacts used for any public binary.

## Local app packaging

`ROADLENS.spec` copies ROADLENS LICENSE/NOTICE and the license files found in the
installed runtime packages into `Contents/Resources/licenses`. Qt frameworks
remain dynamically linked. A directory of notices alone is not full license
compliance: retain upstream notices, satisfy applicable corresponding-source and
relinking requirements, and distribute the exact matching ROADLENS source and
build instructions. Include any additional native-library/codec notices required
by the particular wheel/framework builds. See [the binary release gate](docs/LICENSING.md).
