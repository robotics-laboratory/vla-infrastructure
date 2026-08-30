from pathlib import Path

from tools.verify_piperx_model import verify_model


def test_gate_c_offline_model_verification(tmp_path: Path) -> None:
    result = verify_model(tmp_path)
    assert result["fk_references"] == 2
    assert result["positive_direction_references"] == 6
