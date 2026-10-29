import pytest

from roadlens.cli import parser, run_config
from roadlens.config import Config, SourceConfig, load_config


@pytest.mark.parametrize(
    "change",
    [
        {"threads": 0},
        {"input_size": 123},
        {"confidence": 1},
        {"detection_floor": 0.3},
        {"max_gap": float("nan")},
        {"inference_fps": 0},
        {"read_timeout": -1},
        {"width": 4000},
        {"capture_fps": 121},
        {"threads": True},
        {"confidence": "0.5"},
        {"reconnect_delay": float("inf")},
    ],
)
def test_invalid_config(change):
    with pytest.raises(ValueError):
        Config(**change)


def test_toml_validation(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('threads=3\n[[sources]]\nname="clip"\nkind="video"\nvalue="clip.mp4"\n')
    config = load_config(path)
    assert config.threads == 3
    assert config.sources[0].kind == "video"
    path.write_text("typo=1")
    with pytest.raises(TypeError):
        load_config(path)


def test_sources_and_duplicates():
    source = SourceConfig("phone", "camera", "unique-id")
    with pytest.raises(ValueError):
        Config(sources=(source, source))
    for value in ("-1", "iphone"):
        with pytest.raises(ValueError):
            SourceConfig("fallback", "opencv", value)
    with pytest.raises(ValueError):
        SourceConfig("", "camera", "default")
    with pytest.raises(ValueError):
        SourceConfig("camera", "camera", 0)


def test_cli_sources_and_limits():
    args = parser().parse_args(["run", "--camera", "iphone", "--video", "cars.mp4", "--offline"])
    config = run_config(args)
    assert [s.kind for s in config.sources] == ["camera", "video"]
    assert not config.sources[1].realtime
    assert run_config(parser().parse_args(["run"])).sources[0].value == "default"
    with pytest.raises(ValueError):
        run_config(parser().parse_args(["run", "--max-frames", "0"]))
