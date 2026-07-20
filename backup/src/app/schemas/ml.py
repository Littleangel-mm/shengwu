from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

RegressionAlgorithm = Literal[
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
    "lightgbm",
    "mlp",
]
ClassificationAlgorithm = Literal[
    "logistic",
    "svc",
    "knn",
    "decision_tree",
    "random_forest",
    "extra_trees",
    "gradient_boosting",
    "hist_gradient_boosting",
    "adaboost",
    "bagging",
    "xgboost",
    "lightgbm",
    "mlp",
]
MLAlgorithm = RegressionAlgorithm | ClassificationAlgorithm

REGRESSION_ALGORITHMS: set[str] = {
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
    "lightgbm",
    "mlp",
}
CLASSIFICATION_ALGORITHMS: set[str] = {
    "logistic",
    "svc",
    "knn",
    "decision_tree",
    "random_forest",
    "extra_trees",
    "gradient_boosting",
    "hist_gradient_boosting",
    "adaboost",
    "bagging",
    "xgboost",
    "lightgbm",
    "mlp",
}


def _default_algorithms() -> list[MLAlgorithm]:
    return ["ridge", "random_forest", "gradient_boosting"]


class TargetObjective(BaseModel):
    field_id: UUID
    direction: Literal["maximize", "minimize"] = "maximize"
    weight: float = Field(default=1.0, gt=0, le=100)


DerivedFeatureOp = Literal["ratio", "product", "difference", "sum"]


class DerivedFeatureSpec(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=200)
    op: DerivedFeatureOp
    operands: list[str] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def validate_operands(self) -> "DerivedFeatureSpec":
        if self.op in ("ratio", "difference") and len(self.operands) != 2:
            raise ValueError("比值/差值派生特征需要且仅需要两个操作数")
        return self


class MLRunCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    dataset_version_id: UUID
    task_type: Literal["regression", "classification"] = "regression"
    input_field_ids: list[UUID] = Field(min_length=1, max_length=200)
    target_field_id: UUID | None = None
    targets: list[TargetObjective] | None = Field(default=None, max_length=20)
    derived_features: list[DerivedFeatureSpec] | None = Field(default=None, max_length=50)
    algorithms: list[MLAlgorithm] = Field(
        default_factory=_default_algorithms,
        min_length=1,
        max_length=16,
    )
    random_seed: int = 42
    split_strategy: Literal["group_shuffle_split", "random_split"] = "group_shuffle_split"
    cv_strategy: Literal["group_kfold", "leave_one_group_out", "kfold"] = "group_kfold"
    test_size: float = Field(default=0.2, gt=0.05, lt=0.5)
    numeric_imputer: Literal["median", "mean", "most_frequent"] = "median"
    scaler: Literal["standard", "minmax", "robust", "none"] = "standard"
    cv_folds: int = Field(default=5, ge=2, le=10)
    parameter_search: bool = True
    explain: bool = True
    augmentation_enabled: bool = False
    augmentation_factor: float = Field(default=0.25, gt=0, le=2)
    augmentation_noise_std: float = Field(default=0.02, ge=0, le=0.5)

    @model_validator(mode="after")
    def validate_algorithms(self) -> "MLRunCreate":
        allowed = (
            REGRESSION_ALGORITHMS
            if self.task_type == "regression"
            else CLASSIFICATION_ALGORITHMS
        )
        invalid = sorted(set(self.algorithms) - allowed)
        if invalid:
            raise ValueError(f"算法与任务类型不兼容: {', '.join(invalid)}")
        return self

    @model_validator(mode="after")
    def validate_targets(self) -> "MLRunCreate":
        if self.targets:
            if len(self.targets) > 1 and self.task_type != "regression":
                raise ValueError("多目标加权仅支持回归任务")
            field_ids = [target.field_id for target in self.targets]
            if len(set(field_ids)) != len(field_ids):
                raise ValueError("目标字段不能重复")
        elif self.target_field_id is None:
            raise ValueError("必须指定 target_field_id 或 targets")
        return self

    @property
    def target_specs(self) -> list[TargetObjective]:
        if self.targets:
            return self.targets
        assert self.target_field_id is not None
        return [TargetObjective(field_id=self.target_field_id)]


class PredictionRequest(BaseModel):
    values: dict[str, Any]


class MultiPredictionRequest(BaseModel):
    model_ids: list[UUID] = Field(min_length=1, max_length=50)
    values: dict[str, Any]


class OptimizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    ml_model_id: UUID
    objective: dict[str, Any]
    constraints: dict[str, dict[str, Any]]
    sample_count: int = Field(default=3000, ge=100, le=100000)
    top_n: int = Field(default=20, ge=1, le=500)
    random_seed: int = 42
