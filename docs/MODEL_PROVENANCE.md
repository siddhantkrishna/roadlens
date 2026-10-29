# YOLOv8n model provenance and acquisition

## Exact file used by the verified application

The existing downloader and local test model use:

| Field | Verified value |
| --- | --- |
| Origin | [webml/yolov8n](https://huggingface.co/webml/yolov8n/tree/85bc8d7ab30d4065a41909d756c42819b67b4388) |
| Repository revision | `85bc8d7ab30d4065a41909d756c42819b67b4388` |
| File | `onnx/yolov8n.onnx` |
| Bytes | 12,823,574 |
| SHA-256 | `190ba5f1e61411a001683e349d6b2cdb0804c0dc67a5e34cd8ff6fd00ee54b4d` |
| ONNX producer | `pytorch`, version `2.0.1` |
| ONNX opset | 17 |
| Input | `images`: float tensor `[1, 3, 640, 640]` |
| Output | `output0`: float tensor `[1, 84, 8400]` |

The downloaded file was parsed locally with ONNX tooling; its bytes match the
application's pinned hash. Its embedded metadata declares:

- Description: `Ultralytics YOLOv8n model trained on coco.yaml`
- Author: `Ultralytics`
- Ultralytics version: `8.2.66`
- Export date: `2024-07-26T14:59:23.500291`
- License: `AGPL-3.0 License (https://ultralytics.com/license)`
- Task: `detect`; stride 32; batch 1; image size 640×640; COCO's 80 class names.

These are **embedded declarations**, not independent proof of training or export
history. The pinned hosting revision contains the ONNX file and Git attributes,
but no model card, license file, original editable checkpoint or export script.
The claimed producer/version/date cannot establish the exact original checkpoint,
training inputs, exporter flags or rights held by the uploader.

## Supported existing acquisition

```sh
roadlens fetch-model
```

This uses HTTPS, a fixed revision, a bounded download and SHA-256 verification.
It refuses to overwrite a different existing model. Read the
[AGPL licensing conditions](https://www.ultralytics.com/license) and the
[source/binary release distinction](LICENSING.md). Downloading a file is not a
blanket redistribution clearance. No weights are committed or published by
ROADLENS' source-release procedure.

## Alternative export under upstream terms

Ultralytics documents [ONNX export](https://docs.ultralytics.com/modes/export).
A maintainer who has the necessary rights can create a separately documented
export of the official `yolov8n.pt` model in a compatible PyTorch environment.
Use a separate Linux or supported Apple Silicon environment for export; do not
install PyTorch into the Intel/macOS 3.14 ROADLENS runtime.

```sh
# In a separate, compatible export environment:
python -m pip install ultralytics onnx
yolo export model=yolov8n.pt format=onnx imgsz=640 batch=1 \
  dynamic=False simplify=False opset=17 nms=False
python -m pip freeze > export-environment.txt
shasum -a 256 yolov8n.pt yolov8n.onnx
```

This is the upstream export interface, not a claim that these commands reproduce
the current file byte-for-byte. Before distributing that alternative, record
exact package/source revisions and hashes, trusted checkpoint download URL/hash,
export command, license/notices and corresponding-source availability. Retain
preferred editable weights/source where required. Audit the export environment;
the resulting model must have the raw float COCO contract above.

Test an alternative without replacing the working default:

```sh
roadlens run --video assets/traffic.avi --offline --headless --model /path/to/yolov8n.onnx
ROADLENS_TEST_MODEL=/path/to/yolov8n.onnx QT_QPA_PLATFORM=offscreen python -m pytest -q
```

For desktop use, select its absolute ONNX path in Settings. For CLI footage
validation, also pass `--model` to `roadlens validate-footage`. Changing weights
requires passing the real-image/recording and reviewed crossing tests, retaining
accurate labels and documenting any accuracy difference. Do not silently change
the pinned URL/hash or weaken annotations to make a different model pass.

## Public distribution decision

The application source is published under AGPL-3.0-only with its build scripts,
license, notices and media attribution. The model and generated `.app` are
excluded. An automatic test may download weights into an ephemeral CI runner,
but the workflows do not upload them or an application binary.

**The public app/model gate remains closed** until preferred-source/export
provenance and applicable redistribution/corresponding-source obligations are
resolved with evidence. The metadata improves attribution; it does not remove
that gate. See [LICENSING.md](LICENSING.md) and [RELEASING.md](RELEASING.md).
