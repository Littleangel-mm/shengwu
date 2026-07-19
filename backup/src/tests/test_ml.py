import hashlib

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.schemas.ml import MLRunCreate
from app.services.ml import MLService


def test_ml_configuration_rejects_task_incompatible_algorithm() -> None:
    with pytest.raises(ValidationError):
        MLRunCreate(
            name="classification",
            dataset_version_id="00000000-0000-0000-0000-000000000001",
            task_type="classification",
            input_field_ids=["00000000-0000-0000-0000-000000000002"],
            target_field_id="00000000-0000-0000-0000-000000000003",
            algorithms=["ridge"],
        )


def test_preprocessor_handles_numeric_and_categorical_features() -> None:
    frame = pd.DataFrame(
        {
            "temperature": [20.0, np.nan, 30.0],
            "material": ["A", "B", None],
        }
    )
    processor = MLService._preprocessor(
        {"temperature": "number", "material": "text"},
        {"numeric_imputer": "median", "scaler": "robust"},
    )
    transformed = processor.fit_transform(frame)
    assert transformed.shape == (3, 3)
    assert np.isfinite(transformed).all()


def test_required_regression_algorithms_are_available() -> None:
    for code in ["ridge", "pls", "svr", "random_forest", "gradient_boosting", "xgboost"]:
        assert MLService._regressor(code, 42) is not None


def test_model_parameters_are_valid_json_values() -> None:
    class Estimator:
        def get_params(self, deep: bool = False):
            return {"missing": float("nan"), "learning_rate": 0.1, "callback": object()}

    assert MLService._model_parameters(Estimator()) == {
        "missing": None,
        "learning_rate": 0.1,
    }


def test_model_artifact_hash_is_computed_from_file(tmp_path) -> None:
    artifact = tmp_path / "model.joblib"
    artifact.write_bytes(b"trusted model artifact")
    assert MLService._file_sha256(artifact) == hashlib.sha256(b"trusted model artifact").hexdigest()
