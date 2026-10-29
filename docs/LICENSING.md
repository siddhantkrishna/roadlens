# Licensing and model provenance

ROADLENS original source is **AGPL-3.0-only**; the complete license is in
[LICENSE](../LICENSE) and copyright/attribution notices are in [NOTICE](../NOTICE).
This choice follows the AGPL open-source path stated by Ultralytics for projects
using its YOLO code or models. A file's ONNX format and execution through OpenCV
do not remove the model's license obligations. ROADLENS does not claim an
Ultralytics Enterprise license or offer a permissive license for their weights.

Official references checked for this release preparation:

- [Ultralytics licensing](https://www.ultralytics.com/license)
- [Ultralytics source and AGPL text](https://github.com/ultralytics/ultralytics)
- [GNU AGPL v3](https://www.gnu.org/licenses/agpl-3.0.html)
- [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html)

## The model is a separate download

`roadlens fetch-model` downloads the existing YOLOv8n COCO ONNX export from:

- Repository: [webml/yolov8n](https://huggingface.co/webml/yolov8n)
- Revision: `85bc8d7ab30d4065a41909d756c42819b67b4388`
- Path: `onnx/yolov8n.onnx`
- SHA-256: `190ba5f1e61411a001683e349d6b2cdb0804c0dc67a5e34cd8ff6fd00ee54b4d`
- Upstream architecture/training/export project:
  [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics)

The Git source release excludes all weights and generated app bundles. The
third-party export's pinned revision has no accessible README/model card; its
exact original training/export environment and preferred editable model source
have not been independently established here. [Local ONNX inspection](MODEL_PROVENANCE.md)
records the embedded AGPL declaration, producer, versions and tensor contract;
these declarations do not independently prove the missing chain of provenance. A checksum proves byte identity,
not licensing clearance or reproducibility. Treat the export as subject to the
upstream AGPL terms, not as permissively licensed or independently cleared.

**Binary/model release gate:** do not publicly distribute the existing `.app` or
these ONNX weights until their provenance and corresponding-source obligations
have been resolved. Obtain a documented upstream model source/export recipe and
required notices, or use an export you can reproduce and document from properly
licensed upstream source. Changing the model requires re-running detection,
tracking and reviewed-footage tests; never silently substitute different weights.
This gate applies to app/model distribution; the reviewed AGPL source can be
published separately, with no weights or generated binary.

## Source releases and downstream use

Keep the license, attribution and modification notices, and make source available
under the applicable terms. If distributing a binary, provide the exact matching
ROADLENS source and build/install scripts through the same release location,
plus required corresponding source/notices for covered components. An arbitrary
link to a moving upstream branch is not a complete corresponding-source plan.
Where AGPL network-interaction obligations apply to a modified deployment, users
must be able to obtain its corresponding source. Commercial use is not by
itself prohibited by AGPL; proprietary distribution requires separate rights.
Consult the actual license and Ultralytics' licensing terms for your use case.

## Dependencies and media

Dependency and Qt/Python redistribution details are in
[THIRD_PARTY.md](../THIRD_PARTY.md). Qt frameworks remain dynamically linked;
retain their notices and satisfy LGPL/GPL/commercial terms, including applicable
relinking and corresponding-source requirements. Do not assume the Python
package's top-level license covers every bundled native library.

The Intel clip, Ultralytics photograph and documentation screenshots retain
separate attribution; see [assets/README.md](../assets/README.md) and
[the public-asset manifest](public-assets.json). Original ROADLENS artwork and
UI text are AGPL-3.0-only. Third-party photographs/footage are not relicensed.
