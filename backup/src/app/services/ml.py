import io
import platform
import warnings
from collections import defaultdict
from collections.abc import Callable
from importlib.metadata import version as package_version
from typing import Any
from uuid import UUID

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.cross_decomposition import PLSRegression
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)
from sklearn.model_selection import (
    GridSearchCV,
    GroupKFold,
    GroupShuffleSplit,
    KFold,
    train_test_split,
)
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import (
    LabelEncoder,
    MinMaxScaler,
    OneHotEncoder,
    RobustScaler,
    StandardScaler,
)
from sklearn.svm import SVC, SVR
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import ProcessingJob, Project, StoredFile
from app.schemas.ml import (
    MLRunCreate,
    MultiPredictionRequest,
    OptimizationCreate,
    PredictionRequest,
)
from app.schemas.workflow import TaskAccepted
from app.services.storage import LocalStorage


class MLService:
    def __init__(self, db: Session, storage: LocalStorage) -> None:
        self.db = db
        self.storage = storage

    def create_run(
        self, project_id: UUID, payload: MLRunCreate, actor_id: UUID | None
    ) -> TaskAccepted:
        versions = table(self.db, "dataset_versions")
        datasets = table(self.db, "datasets")
        fields = table(self.db, "dataset_fields")
        version = (
            self.db.execute(
                select(versions)
                .join(datasets, datasets.c.id == versions.c.dataset_id)
                .where(
                    versions.c.id == payload.dataset_version_id,
                    datasets.c.project_id == project_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if not version:
            raise AppError(
                code="dataset_version_not_found", message="数据集版本不存在", status_code=404
            )
        if version["status"] != "frozen":
            raise AppError(
                code="dataset_not_frozen", message="数据集冻结后才能训练", status_code=409
            )
        available = set(
            self.db.scalars(
                select(fields.c.id).where(fields.c.dataset_version_id == payload.dataset_version_id)
            ).all()
        )
        selected = set(payload.input_field_ids) | {payload.target_field_id}
        if not selected.issubset(available):
            raise AppError(
                code="invalid_ml_fields", message="建模字段不属于该数据集版本", status_code=422
            )
        runs = table(self.db, "ml_runs")
        run_fields = table(self.db, "ml_run_fields")
        run_id = self.db.execute(
            insert(runs)
            .values(
                project_id=project_id,
                dataset_version_id=payload.dataset_version_id,
                name=payload.name,
                task_type=payload.task_type,
                status="queued",
                random_seed=payload.random_seed,
                split_strategy="group_shuffle_split",
                group_field_key="source_document_id",
                split_config={"test_size": payload.test_size, "cv_folds": payload.cv_folds},
                preprocessing_config={
                    "numeric_imputer": payload.numeric_imputer,
                    "scaler": payload.scaler,
                    "algorithms": payload.algorithms,
                    "parameter_search": payload.parameter_search,
                    "explain": payload.explain,
                },
                augmentation_config={
                    "enabled": payload.augmentation_enabled,
                    "factor": payload.augmentation_factor,
                    "noise_std": payload.augmentation_noise_std,
                    "scope": "training_only",
                },
                environment_snapshot={},
                metrics_summary={},
                created_by=actor_id,
            )
            .returning(runs.c.id)
        ).scalar_one()
        self.db.execute(
            insert(run_fields),
            [
                {
                    "ml_run_id": run_id,
                    "dataset_field_id": field_id,
                    "role": "input",
                    "position": index,
                    "transformation_config": {},
                }
                for index, field_id in enumerate(payload.input_field_ids)
            ]
            + [
                {
                    "ml_run_id": run_id,
                    "dataset_field_id": payload.target_field_id,
                    "role": "target",
                    "position": 0,
                    "transformation_config": {},
                }
            ],
        )
        job = ProcessingJob(
            project_id=project_id,
            job_type="train_model",
            status="queued",
            progress_percent=0,
            current_stage="waiting",
            idempotency_key=f"train_model:{run_id}",
            requested_config={"ml_run_id": str(run_id)},
            result_summary={},
            requested_by=actor_id,
        )
        self.db.add(job)
        self.db.commit()
        return TaskAccepted(resource_id=run_id, job_id=job.id)

    def list_runs(self, project_id: UUID) -> list[dict]:
        runs = table(self.db, "ml_runs")
        return [
            dict(row)
            for row in self.db.execute(
                select(runs)
                .where(runs.c.project_id == project_id)
                .order_by(runs.c.created_at.desc())
            ).mappings()
        ]

    def get_run(self, project_id: UUID, run_id: UUID) -> dict:
        runs = table(self.db, "ml_runs")
        models = table(self.db, "ml_models")
        metrics = table(self.db, "ml_metrics")
        explanations = table(self.db, "ml_explanations")
        row = (
            self.db.execute(
                select(runs).where(runs.c.id == run_id, runs.c.project_id == project_id)
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppError(code="ml_run_not_found", message="建模任务不存在", status_code=404)
        result = dict(row)
        model_rows = [
            dict(item)
            for item in self.db.execute(
                select(models).where(models.c.ml_run_id == run_id).order_by(models.c.model_no)
            ).mappings()
        ]
        for model in model_rows:
            model["metrics"] = [
                dict(item)
                for item in self.db.execute(
                    select(metrics)
                    .where(metrics.c.ml_model_id == model["id"])
                    .order_by(metrics.c.split_name, metrics.c.metric_name)
                ).mappings()
            ]
            model["explanations"] = [
                dict(item)
                for item in self.db.execute(
                    select(explanations)
                    .where(explanations.c.ml_model_id == model["id"])
                    .order_by(explanations.c.created_at)
                ).mappings()
            ]
        result["models"] = model_rows
        return result

    def _matrix(
        self,
        dataset_version_id: UUID,
        input_ids: list[UUID],
        target_id: UUID,
    ) -> tuple[pd.DataFrame, pd.Series, list[UUID], list[str], str, dict[str, str]]:
        fields = table(self.db, "dataset_fields")
        rows = table(self.db, "dataset_rows")
        cells = table(self.db, "dataset_cells")
        field_rows = self.db.execute(
            select(fields.c.id, fields.c.field_key, fields.c.data_type).where(
                fields.c.id.in_([*input_ids, target_id])
            )
        ).all()
        keys = {field_id: key for field_id, key, _ in field_rows}
        data_types = {key: data_type for _, key, data_type in field_rows}
        values: dict[UUID, dict[UUID, Any]] = defaultdict(dict)
        row_info = self.db.execute(
            select(rows.c.id, rows.c.source_document_id).where(
                rows.c.dataset_version_id == dataset_version_id, rows.c.is_deleted.is_(False)
            )
        ).all()
        row_ids = [row_id for row_id, _ in row_info]
        if row_ids:
            for cell in self.db.execute(
                select(
                    cells.c.row_id, cells.c.field_id, cells.c.value_number, cells.c.value_text
                ).where(
                    cells.c.row_id.in_(row_ids),
                    cells.c.field_id.in_([*input_ids, target_id]),
                    cells.c.is_missing.is_(False),
                )
            ):
                values[cell.row_id][cell.field_id] = (
                    cell.value_number if cell.value_number is not None else cell.value_text
                )
        records = []
        groups = []
        kept_rows = []
        for row_id, document_id in row_info:
            data = values.get(row_id, {})
            if target_id not in data:
                continue
            records.append(
                {keys[field_id]: data.get(field_id) for field_id in input_ids}
                | {keys[target_id]: data[target_id]}
            )
            groups.append(str(document_id or row_id))
            kept_rows.append(row_id)
        frame = pd.DataFrame(records)
        input_keys = [keys[field_id] for field_id in input_ids]
        target_key = keys[target_id]
        if frame.empty:
            raise AppError(
                code="ml_data_empty", message="没有可用于建模的完整目标数据", status_code=422
            )
        numeric_types = {"number", "integer", "float", "decimal"}
        input_types = {key: data_types.get(key, "text") for key in input_keys}
        for key in input_keys:
            if input_types[key] in numeric_types:
                frame[key] = pd.to_numeric(frame[key], errors="coerce")
            else:
                frame[key] = frame[key].astype("string")
        return frame[input_keys], frame[target_key], kept_rows, groups, target_key, input_types

    @staticmethod
    def _regressor(code: str, seed: int):
        from xgboost import XGBRegressor

        models = {
            "ridge": Ridge(alpha=1.0),
            "pls": PLSRegression(n_components=2, scale=False),
            "svr": SVR(kernel="rbf", C=10, epsilon=0.1),
            "random_forest": RandomForestRegressor(
                n_estimators=300, random_state=seed, n_jobs=-1, min_samples_leaf=1
            ),
            "gradient_boosting": GradientBoostingRegressor(random_state=seed),
            "xgboost": XGBRegressor(
                n_estimators=300,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=seed,
                n_jobs=-1,
            ),
            "mlp": MLPRegressor(
                hidden_layer_sizes=(64, 32),
                max_iter=2000,
                early_stopping=False,
                random_state=seed,
            ),
        }
        return models.get(code)

    @staticmethod
    def _classifier(code: str, seed: int):
        from xgboost import XGBClassifier

        models = {
            "logistic": LogisticRegression(max_iter=2000, random_state=seed),
            "svc": SVC(kernel="rbf", C=10, probability=True, random_state=seed),
            "random_forest": RandomForestClassifier(n_estimators=300, random_state=seed, n_jobs=-1),
            "gradient_boosting": GradientBoostingClassifier(random_state=seed),
            "xgboost": XGBClassifier(
                n_estimators=300,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=seed,
                n_jobs=-1,
            ),
            "mlp": MLPClassifier(
                hidden_layer_sizes=(64, 32),
                max_iter=2000,
                early_stopping=False,
                random_state=seed,
            ),
        }
        return models.get(code)

    @staticmethod
    def _preprocessor(input_types: dict[str, str], config: dict[str, Any]) -> ColumnTransformer:
        numeric_types = {"number", "integer", "float", "decimal"}
        numeric = [key for key, data_type in input_types.items() if data_type in numeric_types]
        categorical = [key for key in input_types if key not in numeric]
        scaler_name = config.get("scaler", "standard")
        scalers = {
            "standard": StandardScaler(),
            "minmax": MinMaxScaler(),
            "robust": RobustScaler(),
            "none": "passthrough",
        }
        transformers: list[tuple[str, Any, list[str]]] = []
        if numeric:
            transformers.append(
                (
                    "numeric",
                    Pipeline(
                        [
                            (
                                "imputer",
                                SimpleImputer(strategy=config.get("numeric_imputer", "median")),
                            ),
                            ("scaler", scalers[scaler_name]),
                        ]
                    ),
                    numeric,
                )
            )
        if categorical:
            transformers.append(
                (
                    "categorical",
                    Pipeline(
                        [
                            ("imputer", SimpleImputer(strategy="most_frequent")),
                            (
                                "encoder",
                                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                            ),
                        ]
                    ),
                    categorical,
                )
            )
        return ColumnTransformer(transformers, remainder="drop", verbose_feature_names_out=False)

    @staticmethod
    def _parameter_grid(code: str) -> dict[str, list[Any]]:
        grids: dict[str, dict[str, list[Any]]] = {
            "ridge": {"model__alpha": [0.1, 1.0, 10.0]},
            "pls": {"model__n_components": [1]},
            "svr": {"model__C": [1.0, 10.0], "model__epsilon": [0.05, 0.1]},
            "logistic": {"model__C": [0.1, 1.0, 10.0]},
            "svc": {"model__C": [1.0, 10.0]},
            "random_forest": {"model__max_depth": [None, 8], "model__min_samples_leaf": [1, 2]},
            "gradient_boosting": {
                "model__learning_rate": [0.05, 0.1],
                "model__n_estimators": [100, 200],
            },
            "xgboost": {"model__max_depth": [3, 6], "model__learning_rate": [0.05, 0.1]},
            "mlp": {"model__alpha": [0.0001, 0.001]},
        }
        return grids.get(code, {})

    @staticmethod
    def _augment_training(
        X: pd.DataFrame,
        y: pd.Series,
        groups: list[str],
        input_types: dict[str, str],
        config: dict[str, Any],
        seed: int,
    ) -> tuple[pd.DataFrame, pd.Series, list[str], int]:
        if not config.get("enabled") or X.empty:
            return X, y, groups, 0
        count = max(1, int(len(X) * float(config.get("factor", 0.25))))
        rng = np.random.default_rng(seed)
        sampled = rng.integers(0, len(X), size=count)
        augmented_x = X.iloc[sampled].copy().reset_index(drop=True)
        augmented_y = y.iloc[sampled].copy().reset_index(drop=True)
        numeric_types = {"number", "integer", "float", "decimal"}
        noise_factor = float(config.get("noise_std", 0.02))
        for key, data_type in input_types.items():
            if data_type not in numeric_types or noise_factor <= 0:
                continue
            standard_deviation = float(pd.to_numeric(X[key], errors="coerce").std() or 0)
            if standard_deviation > 0:
                augmented_x[key] = pd.to_numeric(augmented_x[key], errors="coerce") + rng.normal(
                    0, standard_deviation * noise_factor, size=count
                )
        augmented_groups = [groups[int(index)] for index in sampled]
        return (
            pd.concat([X.reset_index(drop=True), augmented_x], ignore_index=True),
            pd.concat([y.reset_index(drop=True), augmented_y], ignore_index=True),
            [*groups, *augmented_groups],
            count,
        )

    @staticmethod
    def _model_parameters(estimator: Any) -> dict[str, Any]:
        parameters: dict[str, Any] = {}
        for key, value in estimator.get_params(deep=False).items():
            if value is None or isinstance(value, (str, int, bool)):
                parameters[key] = value
            elif isinstance(value, float):
                parameters[key] = value if np.isfinite(value) else None
        return parameters

    def train(self, run_id: UUID, progress: Callable[[float, str], None]) -> dict[str, Any]:
        runs = table(self.db, "ml_runs")
        run_fields = table(self.db, "ml_run_fields")
        models_table = table(self.db, "ml_models")
        metrics_table = table(self.db, "ml_metrics")
        predictions_table = table(self.db, "ml_predictions")
        explanations_table = table(self.db, "ml_explanations")
        run = self.db.execute(select(runs).where(runs.c.id == run_id)).mappings().one_or_none()
        if not run:
            raise AppError(code="ml_run_not_found", message="建模任务不存在", status_code=404)
        field_rows = (
            self.db.execute(
                select(run_fields)
                .where(run_fields.c.ml_run_id == run_id)
                .order_by(run_fields.c.role, run_fields.c.position)
            )
            .mappings()
            .all()
        )
        input_ids = [row["dataset_field_id"] for row in field_rows if row["role"] == "input"]
        target_ids = [row["dataset_field_id"] for row in field_rows if row["role"] == "target"]
        if not input_ids or len(target_ids) != 1:
            raise AppError(
                code="invalid_ml_configuration", message="建模输入或目标配置无效", status_code=422
            )
        X, y, row_ids, groups, target_key, input_types = self._matrix(
            run["dataset_version_id"], input_ids, target_ids[0]
        )
        if len(X) < 4:
            raise AppError(
                code="insufficient_samples",
                message="有效样本少于 4 条，无法训练和评估",
                status_code=422,
            )
        label_encoder: LabelEncoder | None = None
        if run["task_type"] == "regression":
            y = pd.to_numeric(y, errors="coerce")
            valid = y.notna()
            X, y = X.loc[valid], y.loc[valid]
            row_ids = [row_id for row_id, keep in zip(row_ids, valid, strict=False) if keep]
            groups = [group for group, keep in zip(groups, valid, strict=False) if keep]
        else:
            label_encoder = LabelEncoder()
            y = pd.Series(label_encoder.fit_transform(y.astype(str)), index=y.index)
        if len(X) < 4:
            raise AppError(
                code="insufficient_samples", message="清理无效目标值后样本不足", status_code=422
            )
        test_size = float((run["split_config"] or {}).get("test_size", 0.2))
        unique_groups = len(set(groups))
        indices = np.arange(len(X))
        if unique_groups >= 2:
            splitter = GroupShuffleSplit(
                n_splits=1, test_size=test_size, random_state=run["random_seed"] or 42
            )
            train_idx, test_idx = next(splitter.split(X, y, groups))
        else:
            train_idx, test_idx = train_test_split(
                indices, test_size=test_size, random_state=run["random_seed"] or 42
            )
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        train_groups = [groups[int(index)] for index in train_idx]
        original_train_samples = len(X_train)
        X_train, y_train, train_groups, augmented_samples = self._augment_training(
            X_train,
            y_train,
            train_groups,
            input_types,
            run["augmentation_config"] or {},
            run["random_seed"] or 42,
        )
        if len(X_test) < 1:
            raise AppError(code="test_set_empty", message="测试集为空", status_code=422)

        self.db.execute(delete(models_table).where(models_table.c.ml_run_id == run_id))
        config = run["preprocessing_config"] or {}
        algorithms = config.get("algorithms", ["ridge", "random_forest"])
        input_keys = list(X.columns)
        best_model_id = None
        best_score = float("inf") if run["task_type"] == "regression" else float("-inf")
        summaries = []
        for index, code in enumerate(algorithms, start=1):
            if code == "mlp" and len(X_train) < 20:
                continue
            estimator = (
                self._regressor(code, run["random_seed"] or 42)
                if run["task_type"] == "regression"
                else self._classifier(code, run["random_seed"] or 42)
            )
            if estimator is None:
                continue
            preprocessor = self._preprocessor(input_types, config)
            pipeline = Pipeline([("preprocessor", preprocessor), ("model", estimator)])
            cv_metric: tuple[str, float] | None = None
            if config.get("parameter_search", True) and len(X_train) >= 4:
                requested_folds = int((run["split_config"] or {}).get("cv_folds", 5))
                unique_train_groups = len(set(train_groups))
                if unique_train_groups >= 2:
                    folds = min(requested_folds, unique_train_groups)
                    cv = GroupKFold(n_splits=folds)
                    fit_groups: list[str] | None = train_groups
                else:
                    folds = min(requested_folds, len(X_train))
                    cv = KFold(n_splits=folds, shuffle=True, random_state=run["random_seed"] or 42)
                    fit_groups = None
                scoring = (
                    "neg_root_mean_squared_error"
                    if run["task_type"] == "regression"
                    else "f1_weighted"
                )
                search = GridSearchCV(
                    pipeline,
                    self._parameter_grid(code),
                    scoring=scoring,
                    cv=cv,
                    n_jobs=-1,
                    error_score="raise",
                )
                if fit_groups is None:
                    search.fit(X_train, y_train)
                else:
                    search.fit(X_train, y_train, groups=fit_groups)
                pipeline = search.best_estimator_
                cv_metric = (
                    "cv_rmse" if run["task_type"] == "regression" else "cv_f1",
                    float(
                        -search.best_score_
                        if run["task_type"] == "regression"
                        else search.best_score_
                    ),
                )
            else:
                pipeline.fit(X_train, y_train)
            predicted = np.asarray(pipeline.predict(X_test)).reshape(-1)
            if run["task_type"] == "regression":
                metric_values = {
                    "r2": float(r2_score(y_test, predicted)) if len(y_test) > 1 else 0.0,
                    "mae": float(mean_absolute_error(y_test, predicted)),
                    "rmse": float(np.sqrt(mean_squared_error(y_test, predicted))),
                }
                selection_score = metric_values["rmse"]
                better = selection_score < best_score
            else:
                metric_values = {
                    "accuracy": float(accuracy_score(y_test, predicted)),
                    "precision": float(
                        precision_score(y_test, predicted, average="weighted", zero_division=0)
                    ),
                    "recall": float(
                        recall_score(y_test, predicted, average="weighted", zero_division=0)
                    ),
                    "f1": float(f1_score(y_test, predicted, average="weighted", zero_division=0)),
                }
                selection_score = metric_values["f1"]
                better = selection_score > best_score
            artifact = {
                "pipeline": pipeline,
                "input_keys": input_keys,
                "target_key": target_key,
                "task_type": run["task_type"],
                "dataset_version_id": str(run["dataset_version_id"]),
                "target_classes": label_encoder.classes_.tolist() if label_encoder else None,
                "residual_std": (
                    float(np.std(np.asarray(y_test, dtype=float) - predicted, ddof=1))
                    if run["task_type"] == "regression" and len(predicted) > 1
                    else 0.0
                ),
            }
            buffer = io.BytesIO()
            joblib.dump(artifact, buffer)
            saved = self.storage.save_bytes(
                run["project_id"],
                category="models",
                extension="joblib",
                content=buffer.getvalue(),
                media_type="application/octet-stream",
            )
            project = self.db.get(Project, run["project_id"])
            if not project:
                raise AppError(code="project_not_found", message="项目不存在", status_code=404)
            stored = StoredFile(
                organization_id=project.organization_id,
                project_id=run["project_id"],
                storage_provider="local",
                storage_key=saved.storage_key,
                original_name=f"{code}-{run_id}.joblib",
                safe_name=saved.safe_name,
                extension="joblib",
                media_type=saved.media_type,
                byte_size=saved.byte_size,
                sha256=saved.sha256,
                purpose="model",
                security_status="generated",
                metadata_json={},
            )
            self.db.add(stored)
            self.db.flush()
            model_id = self.db.execute(
                insert(models_table)
                .values(
                    ml_run_id=run_id,
                    model_no=index,
                    display_name=code.replace("_", " ").title(),
                    algorithm_code=code,
                    algorithm_version=(
                        package_version("xgboost") if code == "xgboost" else sklearn.__version__
                    ),
                    status="completed",
                    hyperparameters=self._model_parameters(pipeline.named_steps["model"]),
                    fitted_parameters={},
                    artifact_file_id=stored.id,
                    artifact_sha256=saved.sha256,
                    is_selected=False,
                    metadata={
                        "augmentation": {
                            "enabled": augmented_samples > 0,
                            "generated_samples": augmented_samples,
                            "training_only": True,
                        }
                    },
                    completed_at=func.now(),
                )
                .returning(models_table.c.id)
            ).scalar_one()
            self.db.execute(
                insert(metrics_table),
                [
                    {
                        "ml_model_id": model_id,
                        "dataset_field_id": target_ids[0],
                        "split_name": "test",
                        "metric_name": name,
                        "metric_value": value,
                        "metric_payload": {},
                    }
                    for name, value in metric_values.items()
                ]
                + (
                    [
                        {
                            "ml_model_id": model_id,
                            "dataset_field_id": target_ids[0],
                            "split_name": "cross_validation",
                            "metric_name": cv_metric[0],
                            "metric_value": cv_metric[1],
                            "metric_payload": {"folds": folds},
                        }
                    ]
                    if cv_metric
                    else []
                ),
            )
            self.db.execute(
                insert(predictions_table),
                [
                    {
                        "ml_model_id": model_id,
                        "dataset_row_id": row_ids[int(source_index)],
                        "target_field_id": target_ids[0],
                        "split_name": "test",
                        "actual_value": {
                            "value": actual.item() if hasattr(actual, "item") else actual
                        },
                        "predicted_value": {
                            "value": pred.item() if hasattr(pred, "item") else pred
                        },
                        "residual_value": float(actual - pred)
                        if run["task_type"] == "regression"
                        else None,
                        "metadata": {},
                    }
                    for source_index, actual, pred in zip(test_idx, y_test, predicted, strict=False)
                ],
            )
            if config.get("explain", True):
                scoring = (
                    "neg_root_mean_squared_error"
                    if run["task_type"] == "regression"
                    else "f1_weighted"
                )
                importance = permutation_importance(
                    pipeline,
                    X_test,
                    y_test,
                    scoring=scoring,
                    n_repeats=5,
                    random_state=run["random_seed"] or 42,
                )
                self.db.execute(
                    insert(explanations_table).values(
                        ml_model_id=model_id,
                        method="permutation_importance",
                        scope="global",
                        explanation_data={
                            "features": [
                                {
                                    "name": key,
                                    "importance_mean": float(importance.importances_mean[position]),
                                    "importance_std": float(importance.importances_std[position]),
                                }
                                for position, key in enumerate(input_keys)
                            ],
                            "scoring": scoring,
                            "sample_count": len(X_test),
                        },
                    )
                )
                transformed_train = pipeline.named_steps["preprocessor"].transform(X_train)
                transformed_test = pipeline.named_steps["preprocessor"].transform(X_test)
                feature_names = list(pipeline.named_steps["preprocessor"].get_feature_names_out())
                background = np.asarray(transformed_train)[: min(30, len(transformed_train))]
                explained = np.asarray(transformed_test)[: min(30, len(transformed_test))]
                fitted_model = pipeline.named_steps["model"]
                predictor = (
                    fitted_model.predict_proba
                    if run["task_type"] == "classification"
                    and hasattr(fitted_model, "predict_proba")
                    else fitted_model.predict
                )
                import shap

                explainer = shap.Explainer(
                    predictor, background, feature_names=feature_names, algorithm="permutation"
                )
                shap_values = np.asarray(
                    explainer(explained, max_evals=max(2 * len(feature_names) + 1, 11)).values
                )
                reduce_axes = (0,) + tuple(range(2, shap_values.ndim))
                mean_absolute = np.mean(np.abs(shap_values), axis=reduce_axes)
                self.db.execute(
                    insert(explanations_table).values(
                        ml_model_id=model_id,
                        method="shap",
                        scope="global",
                        explanation_data={
                            "features": [
                                {"name": name, "mean_absolute_shap": float(mean_absolute[position])}
                                for position, name in enumerate(feature_names)
                            ],
                            "sample_count": len(explained),
                            "background_count": len(background),
                        },
                    )
                )
            summaries.append(
                {
                    "model_id": str(model_id),
                    "algorithm": code,
                    "metrics": metric_values,
                    "cross_validation": {cv_metric[0]: cv_metric[1]} if cv_metric else None,
                    "explained": bool(config.get("explain", True)),
                }
            )
            if better:
                best_score, best_model_id = selection_score, model_id
            progress(10 + 80 * index / max(len(algorithms), 1), f"training_{code}")
            self.db.commit()
        if not best_model_id:
            raise AppError(
                code="no_supported_models", message="没有可执行的模型算法", status_code=422
            )
        self.db.execute(
            update(models_table)
            .where(models_table.c.id == best_model_id)
            .values(is_selected=True, selection_reason="best_test_metric")
        )
        summary = {
            "models": summaries,
            "selected_model_id": str(best_model_id),
            "samples": len(X),
            "train_samples": len(train_idx),
            "original_train_samples": original_train_samples,
            "augmented_samples": augmented_samples,
            "test_samples": len(test_idx),
        }
        self.db.execute(
            update(runs)
            .where(runs.c.id == run_id)
            .values(
                status="completed",
                environment_snapshot={
                    "python": platform.python_version(),
                    "sklearn": sklearn.__version__,
                    "pandas": pd.__version__,
                    "xgboost": package_version("xgboost"),
                    "shap": package_version("shap"),
                },
                metrics_summary=summary,
                completed_at=func.now(),
            )
        )
        self.db.commit()
        return summary

    def select_model(self, project_id: UUID, run_id: UUID, model_id: UUID) -> dict:
        runs = table(self.db, "ml_runs")
        models = table(self.db, "ml_models")
        model = (
            self.db.execute(
                select(models)
                .join(runs, runs.c.id == models.c.ml_run_id)
                .where(
                    runs.c.id == run_id,
                    runs.c.project_id == project_id,
                    models.c.id == model_id,
                    models.c.status == "completed",
                )
            )
            .mappings()
            .one_or_none()
        )
        if not model:
            raise AppError(
                code="ml_model_not_found", message="模型不存在或尚未完成", status_code=404
            )
        self.db.execute(
            update(models)
            .where(models.c.ml_run_id == run_id)
            .values(is_selected=False, selection_reason=None)
        )
        self.db.execute(
            update(models)
            .where(models.c.id == model_id)
            .values(is_selected=True, selection_reason="selected_by_user")
        )
        self.db.commit()
        return {
            "run_id": run_id,
            "selected_model_id": model_id,
            "selection_reason": "selected_by_user",
        }

    def _load_model(self, project_id: UUID, model_id: UUID) -> tuple[dict, dict]:
        models = table(self.db, "ml_models")
        runs = table(self.db, "ml_runs")
        row = (
            self.db.execute(
                select(models, runs.c.project_id)
                .join(runs, runs.c.id == models.c.ml_run_id)
                .where(models.c.id == model_id, runs.c.project_id == project_id)
            )
            .mappings()
            .one_or_none()
        )
        if not row or not row["artifact_file_id"]:
            raise AppError(
                code="ml_model_not_found", message="模型不存在或尚未生成", status_code=404
            )
        stored = self.db.get(StoredFile, row["artifact_file_id"])
        if not stored:
            raise AppError(code="ml_artifact_not_found", message="模型文件不存在", status_code=404)
        artifact = joblib.load(self.storage.path_for_key(stored.storage_key))
        return dict(row), artifact

    @staticmethod
    def _predict_with_uncertainty(
        artifact: dict[str, Any], frame: pd.DataFrame
    ) -> tuple[np.ndarray, list[dict[str, Any]]]:
        pipeline = artifact["pipeline"]
        predictions = np.asarray(pipeline.predict(frame)).reshape(-1)
        estimator = pipeline.named_steps["model"]
        uncertainties: list[dict[str, Any]] = []
        if artifact["task_type"] == "classification" and hasattr(estimator, "predict_proba"):
            transformed = pipeline.named_steps["preprocessor"].transform(frame)
            probabilities = np.asarray(estimator.predict_proba(transformed))
            for row in probabilities:
                safe = np.clip(row, 1e-12, 1)
                uncertainties.append(
                    {
                        "confidence": float(np.max(row)),
                        "entropy": float(-np.sum(safe * np.log(safe))),
                        "probabilities": [float(value) for value in row],
                    }
                )
            return predictions, uncertainties
        standard_deviations: np.ndarray | None = None
        if hasattr(estimator, "estimators_") and artifact["task_type"] == "regression":
            transformed = pipeline.named_steps["preprocessor"].transform(frame)
            estimators = np.asarray(estimator.estimators_, dtype=object).reshape(-1)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                tree_predictions = np.asarray(
                    [np.asarray(tree.predict(transformed)).reshape(-1) for tree in estimators]
                )
            if tree_predictions.shape[0] > 1:
                standard_deviations = np.std(tree_predictions, axis=0, ddof=1)
        if standard_deviations is None:
            standard_deviations = np.full(
                len(predictions), float(artifact.get("residual_std") or 0.0)
            )
        for prediction, standard_deviation in zip(predictions, standard_deviations, strict=False):
            uncertainties.append(
                {
                    "standard_deviation": float(standard_deviation),
                    "prediction_interval_95": [
                        float(prediction - 1.96 * standard_deviation),
                        float(prediction + 1.96 * standard_deviation),
                    ],
                    "method": "ensemble_spread"
                    if hasattr(estimator, "estimators_")
                    else "test_residual",
                }
            )
        return predictions, uncertainties

    def predict(self, project_id: UUID, model_id: UUID, payload: PredictionRequest) -> dict:
        model, artifact = self._load_model(project_id, model_id)
        missing = [key for key in artifact["input_keys"] if key not in payload.values]
        if missing:
            raise AppError(
                code="missing_prediction_inputs",
                message="缺少模型输入字段",
                status_code=422,
                details=missing,
            )
        frame = pd.DataFrame([{key: payload.values[key] for key in artifact["input_keys"]}])
        predictions, uncertainties = self._predict_with_uncertainty(artifact, frame)
        prediction = predictions[0]
        value = prediction.item() if hasattr(prediction, "item") else prediction
        if artifact.get("target_classes") is not None:
            value = artifact["target_classes"][int(value)]
        return {
            "model_id": model_id,
            "target": artifact["target_key"],
            "prediction": value,
            "task_type": artifact["task_type"],
            "uncertainty": uncertainties[0],
        }

    def predict_many(self, project_id: UUID, payload: MultiPredictionRequest) -> dict:
        predictions = []
        for model_id in dict.fromkeys(payload.model_ids):
            result = self.predict(project_id, model_id, PredictionRequest(values=payload.values))
            predictions.append(result)
        return {"predictions": predictions, "count": len(predictions)}

    def create_optimization(
        self, project_id: UUID, payload: OptimizationCreate, actor_id: UUID | None
    ) -> TaskAccepted:
        _, artifact = self._load_model(project_id, payload.ml_model_id)
        if artifact["task_type"] != "regression":
            raise AppError(
                code="optimization_requires_regression",
                message="反向优化仅支持回归模型",
                status_code=422,
            )
        runs = table(self.db, "optimization_runs")
        run_id = self.db.execute(
            insert(runs)
            .values(
                project_id=project_id,
                ml_model_id=payload.ml_model_id,
                name=payload.name,
                method="random_search",
                status="queued",
                objective_config=payload.objective,
                constraint_config=payload.constraints,
                search_config={
                    "sample_count": payload.sample_count,
                    "top_n": payload.top_n,
                    "random_seed": payload.random_seed,
                },
                result_summary={},
                created_by=actor_id,
            )
            .returning(runs.c.id)
        ).scalar_one()
        job = ProcessingJob(
            project_id=project_id,
            job_type="run_optimization",
            status="queued",
            progress_percent=0,
            current_stage="waiting",
            idempotency_key=f"run_optimization:{run_id}",
            requested_config={"optimization_run_id": str(run_id)},
            result_summary={},
            requested_by=actor_id,
        )
        self.db.add(job)
        self.db.commit()
        return TaskAccepted(resource_id=run_id, job_id=job.id)

    def optimize(self, run_id: UUID, progress: Callable[[float, str], None]) -> dict[str, Any]:
        runs = table(self.db, "optimization_runs")
        candidates = table(self.db, "optimization_candidates")
        run = self.db.execute(select(runs).where(runs.c.id == run_id)).mappings().one_or_none()
        if not run:
            raise AppError(code="optimization_not_found", message="优化任务不存在", status_code=404)
        _, artifact = self._load_model(run["project_id"], run["ml_model_id"])
        constraints = run["constraint_config"] or {}
        missing = [key for key in artifact["input_keys"] if key not in constraints]
        if missing:
            raise AppError(
                code="optimization_constraints_missing",
                message="缺少输入约束",
                status_code=422,
                details=missing,
            )
        config = run["search_config"] or {}
        sample_count = int(config.get("sample_count", 3000))
        rng = np.random.default_rng(int(config.get("random_seed", 42)))
        data = {}
        for key in artifact["input_keys"]:
            rule = constraints[key]
            if "values" in rule:
                data[key] = rng.choice(rule["values"], size=sample_count)
            else:
                data[key] = rng.uniform(float(rule["min"]), float(rule["max"]), size=sample_count)
        frame = pd.DataFrame(data)
        progress(35, "predicting_candidates")
        predicted, uncertainty_rows = self._predict_with_uncertainty(artifact, frame)
        objective = run["objective_config"] or {}
        direction = objective.get("direction", "target")
        if direction == "maximize":
            scores = -np.asarray(predicted, dtype=float)
        elif direction == "minimize":
            scores = np.asarray(predicted, dtype=float)
        else:
            target = float(objective.get("target", 0))
            scores = np.square(np.asarray(predicted, dtype=float) - target)
        top_n = min(int(config.get("top_n", 20)), sample_count)
        top_indices = np.argsort(scores)[:top_n]
        self.db.execute(delete(candidates).where(candidates.c.optimization_run_id == run_id))
        rows = []
        for rank, idx in enumerate(top_indices, start=1):
            inputs = {
                key: frame.iloc[int(idx)][key].item()
                if hasattr(frame.iloc[int(idx)][key], "item")
                else frame.iloc[int(idx)][key]
                for key in artifact["input_keys"]
            }
            pred = predicted[int(idx)]
            rows.append(
                {
                    "optimization_run_id": run_id,
                    "rank_no": rank,
                    "input_values": inputs,
                    "predicted_values": {
                        artifact["target_key"]: pred.item() if hasattr(pred, "item") else pred
                    },
                    "uncertainty": uncertainty_rows[int(idx)],
                    "objective_score": float(scores[int(idx)]),
                    "is_feasible": True,
                    "constraint_violations": [],
                    "metadata": {},
                }
            )
        self.db.execute(insert(candidates), rows)
        summary = {
            "candidate_count": top_n,
            "evaluated": sample_count,
            "best": (
                {
                    "input_values": rows[0]["input_values"],
                    "predicted_values": rows[0]["predicted_values"],
                    "objective_score": rows[0]["objective_score"],
                    "uncertainty": rows[0]["uncertainty"],
                }
                if rows
                else None
            ),
        }
        self.db.execute(
            update(runs)
            .where(runs.c.id == run_id)
            .values(status="completed", result_summary=summary, completed_at=func.now())
        )
        self.db.commit()
        progress(100, "completed")
        return summary

    def get_optimization(self, project_id: UUID, run_id: UUID) -> dict:
        runs = table(self.db, "optimization_runs")
        candidates = table(self.db, "optimization_candidates")
        row = (
            self.db.execute(
                select(runs).where(runs.c.id == run_id, runs.c.project_id == project_id)
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppError(code="optimization_not_found", message="优化任务不存在", status_code=404)
        result = dict(row)
        result["candidates"] = [
            dict(item)
            for item in self.db.execute(
                select(candidates)
                .where(candidates.c.optimization_run_id == run_id)
                .order_by(candidates.c.rank_no)
            ).mappings()
        ]
        return result
