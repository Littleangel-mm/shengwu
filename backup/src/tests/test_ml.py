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


def test_ml_configuration_uses_safe_grouped_split_by_default() -> None:
    payload = MLRunCreate(
        name="grouped",
        dataset_version_id="00000000-0000-0000-0000-000000000001",
        input_field_ids=["00000000-0000-0000-0000-000000000002"],
        target_field_id="00000000-0000-0000-0000-000000000003",
    )
    assert payload.split_strategy == "group_shuffle_split"


def test_ml_configuration_allows_explicit_random_split() -> None:
    payload = MLRunCreate(
        name="random",
        dataset_version_id="00000000-0000-0000-0000-000000000001",
        input_field_ids=["00000000-0000-0000-0000-000000000002"],
        target_field_id="00000000-0000-0000-0000-000000000003",
        split_strategy="random_split",
    )
    assert payload.split_strategy == "random_split"


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


def test_extended_regression_registry_covers_fourteen_models() -> None:
    codes = [
        "ridge",
        "lasso",
        "elastic_net",
        "pls",
        "svr",
        "knn",
        "decision_tree",
        "random_forest",
        "extra_trees",
        "gradient_boosting",
        "hist_gradient_boosting",
        "adaboost",
        "bagging",
        "xgboost",
    ]
    available = [code for code in codes if MLService._regressor(code, 42) is not None]
    assert len(available) >= 14


def test_resolve_cv_uses_group_kfold_with_enough_groups() -> None:
    groups = ["a", "a", "b", "b", "c", "c"]
    cv, fit_groups, folds, warning = MLService._resolve_cv("group_kfold", 5, groups, 6, 42)
    assert type(cv).__name__ == "GroupKFold"
    assert fit_groups == groups
    assert folds == 3
    assert warning is None


def test_resolve_cv_leave_one_group_out() -> None:
    groups = ["a", "a", "b", "b", "c", "c"]
    cv, fit_groups, _folds, warning = MLService._resolve_cv(
        "leave_one_group_out", 5, groups, 6, 42
    )
    assert type(cv).__name__ == "LeaveOneGroupOut"
    assert fit_groups == groups
    assert warning is None


def test_resolve_cv_degrades_explicitly_when_groups_insufficient() -> None:
    groups = ["only", "only", "only", "only"]
    cv, fit_groups, _folds, warning = MLService._resolve_cv("group_kfold", 5, groups, 4, 42)
    assert type(cv).__name__ == "KFold"
    assert fit_groups is None
    assert warning is not None


def test_cross_validate_returns_out_of_fold_predictions_for_every_row() -> None:
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import KFold
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    frame = pd.DataFrame({"x": [float(value) for value in range(12)]})
    target = pd.Series([2.0 * value + 1 for value in range(12)])
    pipeline = Pipeline([("scaler", StandardScaler()), ("model", Ridge(alpha=0.1))])
    service = MLService.__new__(MLService)
    fold_metrics, positions, predictions = service._cross_validate(
        pipeline,
        frame,
        target,
        KFold(n_splits=3, shuffle=True, random_state=42),
        None,
        "regression",
    )
    assert len(fold_metrics) == 3
    assert sorted(positions) == list(range(12))
    assert len(predictions) == 12
    assert all("cv_rmse" in fold for fold in fold_metrics)


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
