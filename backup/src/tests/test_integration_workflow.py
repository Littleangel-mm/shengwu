import io
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires an isolated PostgreSQL acceptance database",
)


def test_complete_backend_workflow() -> None:
    from app.core.config import get_settings
    from app.main import app

    client = TestClient(app)

    def checked(response, expected=200):
        assert response.status_code == expected, response.text
        return response.json() if response.content else None

    checked(client.get("/api/v1/health/live"))
    checked(client.get("/api/v1/health/ready"))
    checked(client.get("/api/v1/health/ocr"))

    owner = checked(
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "integration-owner@example.com",
                "display_name": "Integration Owner",
                "password": "StrongPassword123!",
            },
        ),
        201,
    )
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    get_settings().platform_admin_user_ids = owner["user"]["id"]
    checked(client.get("/api/v1/auth/me", headers=headers))
    organization = checked(
        client.post(
            "/api/v1/organizations",
            headers=headers,
            json={"name": "Integration Organization", "slug": "integration-organization"},
        ),
        201,
    )
    project = checked(
        client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "organization_id": organization["id"],
                "name": "Generic Research Integration",
                "research_domain": "general biotechnology",
            },
        ),
        201,
    )
    project_id = project["id"]
    other_project = checked(
        client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "organization_id": organization["id"],
                "name": "Report Isolation Target",
                "research_domain": "security validation",
            },
        ),
        201,
    )
    checked(client.get("/api/v1/organizations", headers=headers))
    checked(client.get("/api/v1/projects", headers=headers))
    checked(
        client.patch(
            f"/api/v1/projects/{project_id}", headers=headers, json={"description": "updated"}
        )
    )
    source_unit = checked(
        client.post(
            "/api/v1/units",
            headers=headers,
            json={
                "code": "integration_celsius",
                "symbol": "iC",
                "name": "Integration Celsius",
                "dimension": "temperature",
            },
        ),
        201,
    )
    target_unit = checked(
        client.post(
            "/api/v1/units",
            headers=headers,
            json={
                "code": "integration_kelvin",
                "symbol": "iK",
                "name": "Integration Kelvin",
                "dimension": "temperature",
            },
        ),
        201,
    )
    conversion_rule = checked(
        client.post(
            f"/api/v1/conversion-rules?organization_id={organization['id']}",
            headers=headers,
            json={
                "source_unit_id": source_unit["id"],
                "target_unit_id": target_unit["id"],
                "rule_name": "Celsius to Kelvin",
                "multiplier": 1,
                "offset_value": 273.15,
            },
        ),
        201,
    )
    converted = checked(
        client.post(
            "/api/v1/convert",
            headers=headers,
            json={"rule_id": conversion_rule["id"], "value": 25, "confirmed": True},
        )
    )
    assert converted["target_value"] == pytest.approx(298.15)
    checked(client.get("/api/v1/units", headers=headers))
    checked(
        client.post(
            f"/api/v1/organizations/{organization['id']}/external-services",
            headers=headers,
            json={
                "service_type": "translation",
                "provider": "deepseek",
                "name": "Integration translation",
                "secret_reference": "DEEPSEEK_API_KEY",
            },
        ),
        201,
    )
    checked(
        client.get(f"/api/v1/organizations/{organization['id']}/external-services", headers=headers)
    )

    outsider = checked(
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "integration-outsider@example.com",
                "display_name": "Outsider",
                "password": "StrongPassword123!",
            },
        ),
        201,
    )
    outsider_headers = {"Authorization": f"Bearer {outsider['access_token']}"}
    assert client.get(f"/api/v1/projects/{project_id}", headers=outsider_headers).status_code == 404
    assert (
        client.get(
            f"/api/v1/projects/{project_id}/audit-logs",
            headers=outsider_headers,
        ).status_code
        == 404
    )

    document_ids = []
    for index in range(8):
        content = (
            f"处理组: G{index} 发酵时间 {24 + index} h 温度 {20 + index} ℃ "
            f"产率 {40 + index * 2} %。\n"
            f"Treatment group G{index}, fermentation temperature {20 + index} C and yield {40 + index * 2} percent."
        ).encode()
        uploaded = checked(
            client.post(
                f"/api/v1/projects/{project_id}/documents/upload",
                headers=headers,
                files=[("files", (f"paper-{index}.txt", io.BytesIO(content), "text/plain"))],
            )
        )
        item = uploaded["items"][0]
        checked(
            client.post(f"/api/v1/projects/{project_id}/jobs/{item['job_id']}/run", headers=headers)
        )
        document_ids.append(item["document_id"])

    checked(client.get(f"/api/v1/projects/{project_id}/documents", headers=headers))
    checked(
        client.get(f"/api/v1/projects/{project_id}/documents/{document_ids[0]}", headers=headers)
    )

    first_version = checked(
        client.post(
            f"/api/v1/projects/{project_id}/documents/upload",
            headers=headers,
            files=[("files", ("versioned.txt", io.BytesIO(b"first version"), "text/plain"))],
        )
    )["items"][0]
    second_version = checked(
        client.post(
            f"/api/v1/projects/{project_id}/documents/upload",
            headers=headers,
            files=[("files", ("versioned.txt", io.BytesIO(b"second version"), "text/plain"))],
        )
    )["items"][0]
    assert first_version["document_id"] == second_version["document_id"]
    assert first_version["document_version_id"] != second_version["document_version_id"]

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("nested/imported.txt", "温度 30 ℃ 产率 60 %")
    archive_buffer.seek(0)
    archive_result = checked(
        client.post(
            f"/api/v1/projects/{project_id}/documents/upload",
            headers=headers,
            files=[("files", ("papers.zip", archive_buffer, "application/zip"))],
        )
    )
    assert archive_result["total"] == 2

    search = checked(
        client.post(
            f"/api/v1/projects/{project_id}/search-runs",
            headers=headers,
            json={
                "name": "temperature and yield",
                "terms": ["温度", "产率"],
                "logic_operator": "AND",
                "search_mode": "hybrid",
                "semantic_threshold": 0.1,
            },
        ),
        202,
    )
    checked(
        client.post(f"/api/v1/projects/{project_id}/jobs/{search['job_id']}/run", headers=headers)
    )
    results = checked(
        client.get(
            f"/api/v1/projects/{project_id}/search-runs/{search['resource_id']}/results",
            headers=headers,
        )
    )
    assert results["total"] >= 8
    reviewed = results["items"][0]
    checked(
        client.patch(
            f"/api/v1/projects/{project_id}/search-runs/{search['resource_id']}/results/{reviewed['id']}",
            headers=headers,
            json={"is_included": False, "review_status": "excluded"},
        )
    )

    category = checked(
        client.post(
            f"/api/v1/projects/{project_id}/term-categories",
            headers=headers,
            json={"code": "measure", "name": "Measurements"},
        ),
        201,
    )

    def create_term(name):
        return checked(
            client.post(
                f"/api/v1/projects/{project_id}/terms",
                headers=headers,
                json={
                    "category_id": category["id"],
                    "canonical_name": name,
                    "semantic_role": "feature",
                    "data_type": "number",
                    "aliases": [],
                },
            ),
            201,
        )

    temperature_term = create_term("温度")
    source_term = create_term("发酵温度")
    yield_term = create_term("产率")
    checked(
        client.post(
            f"/api/v1/projects/{project_id}/terms/merge",
            headers=headers,
            json={
                "target_term_id": temperature_term["id"],
                "source_term_ids": [source_term["id"]],
                "reason": "equivalent terms",
            },
        )
    )
    split_source = create_term("指标")
    split_children = checked(
        client.post(
            f"/api/v1/projects/{project_id}/terms/{split_source['id']}/split",
            headers=headers,
            json={
                "children": [
                    {"category_id": category["id"], "canonical_name": "指标甲"},
                    {"category_id": category["id"], "canonical_name": "指标乙"},
                ]
            },
        )
    )
    checked(
        client.delete(
            f"/api/v1/projects/{project_id}/terms/{split_children[1]['id']}", headers=headers
        )
    )

    field_schema = checked(
        client.post(
            f"/api/v1/projects/{project_id}/field-schemas",
            headers=headers,
            json={
                "name": "Integration fields",
                "source_search_run_id": search["resource_id"],
                "fields": [
                    {
                        "field_key": "temperature",
                        "display_name": "温度",
                        "source_term_id": temperature_term["id"],
                        "semantic_role": "feature",
                        "data_type": "number",
                        "include_in_model": True,
                    },
                    {
                        "field_key": "yield_value",
                        "display_name": "产率",
                        "source_term_id": yield_term["id"],
                        "semantic_role": "target",
                        "data_type": "number",
                        "include_in_model": True,
                    },
                ],
            },
        ),
        201,
    )
    checked(
        client.post(
            f"/api/v1/projects/{project_id}/field-schemas/{field_schema['id']}/freeze",
            headers=headers,
        )
    )
    extraction = checked(
        client.post(
            f"/api/v1/projects/{project_id}/extraction-runs",
            headers=headers,
            json={"name": "Integration extraction", "field_schema_id": field_schema["id"]},
        ),
        202,
    )
    checked(
        client.post(
            f"/api/v1/projects/{project_id}/jobs/{extraction['job_id']}/run", headers=headers
        )
    )
    extraction_records = checked(
        client.get(
            f"/api/v1/projects/{project_id}/extraction-runs/{extraction['resource_id']}/records",
            headers=headers,
        )
    )
    assert extraction_records["total"] >= 16

    dataset = checked(
        client.post(
            f"/api/v1/projects/{project_id}/datasets/from-extraction",
            headers=headers,
            json={
                "name": "Integration dataset",
                "extraction_run_id": extraction["resource_id"],
            },
        ),
        202,
    )
    checked(
        client.post(f"/api/v1/projects/{project_id}/jobs/{dataset['job_id']}/run", headers=headers)
    )
    version = checked(
        client.get(
            f"/api/v1/projects/{project_id}/dataset-versions/{dataset['resource_id']}",
            headers=headers,
        )
    )
    checked(
        client.post(
            f"/api/v1/projects/{project_id}/dataset-versions/{dataset['resource_id']}/freeze",
            headers=headers,
        )
    )
    cloned = checked(
        client.post(
            f"/api/v1/projects/{project_id}/dataset-versions/{dataset['resource_id']}/clone",
            headers=headers,
            json={"change_summary": "second review round"},
        ),
        201,
    )
    assert cloned["version_no"] == 2
    exported = client.get(
        f"/api/v1/projects/{project_id}/dataset-versions/{dataset['resource_id']}/export.xlsx",
        headers=headers,
    )
    assert exported.status_code == 200 and exported.content.startswith(b"PK")

    field_ids = {field["field_key"]: field["id"] for field in version["fields"]}
    ml_run = checked(
        client.post(
            f"/api/v1/projects/{project_id}/ml-runs",
            headers=headers,
            json={
                "name": "Integration model",
                "dataset_version_id": dataset["resource_id"],
                "input_field_ids": [field_ids["temperature"]],
                "target_field_id": field_ids["yield_value"],
                "algorithms": ["ridge", "random_forest"],
                "parameter_search": False,
                "explain": False,
                "augmentation_enabled": True,
            },
        ),
        202,
    )
    checked(
        client.post(f"/api/v1/projects/{project_id}/jobs/{ml_run['job_id']}/run", headers=headers)
    )
    ml_detail = checked(
        client.get(
            f"/api/v1/projects/{project_id}/ml-runs/{ml_run['resource_id']}", headers=headers
        )
    )
    assert len(ml_detail["models"]) == 2
    model_ids = [model["id"] for model in ml_detail["models"]]
    checked(
        client.post(
            f"/api/v1/projects/{project_id}/ml-runs/{ml_run['resource_id']}/models/{model_ids[0]}/select",
            headers=headers,
        )
    )
    prediction = checked(
        client.post(
            f"/api/v1/projects/{project_id}/ml-models/{model_ids[0]}/predict",
            headers=headers,
            json={"values": {"temperature": 26}},
        )
    )
    assert "prediction_interval_95" in prediction["uncertainty"]
    many = checked(
        client.post(
            f"/api/v1/projects/{project_id}/ml-models/predict-many",
            headers=headers,
            json={"model_ids": model_ids, "values": {"temperature": 26}},
        )
    )
    assert many["count"] == 2
    optimization = checked(
        client.post(
            f"/api/v1/projects/{project_id}/optimization-runs",
            headers=headers,
            json={
                "name": "Integration optimization",
                "ml_model_id": model_ids[1],
                "objective": {"direction": "maximize"},
                "constraints": {"temperature": {"min": 20, "max": 35}},
                "sample_count": 100,
                "top_n": 5,
            },
        ),
        202,
    )
    checked(
        client.post(
            f"/api/v1/projects/{project_id}/jobs/{optimization['job_id']}/run", headers=headers
        )
    )
    optimized = checked(
        client.get(
            f"/api/v1/projects/{project_id}/optimization-runs/{optimization['resource_id']}",
            headers=headers,
        )
    )
    assert optimized["candidates"][0]["uncertainty"]

    report = checked(
        client.post(
            f"/api/v1/projects/{project_id}/reports",
            headers=headers,
            json={
                "title": "Integration report",
                "dataset_version_id": dataset["resource_id"],
                "ml_run_id": ml_run["resource_id"],
                "optimization_run_id": optimization["resource_id"],
            },
        ),
        202,
    )
    cross_project_report = client.post(
        f"/api/v1/projects/{other_project['id']}/reports",
        headers=headers,
        json={
            "title": "Cross-project report must fail",
            "dataset_version_id": dataset["resource_id"],
            "ml_run_id": ml_run["resource_id"],
            "optimization_run_id": optimization["resource_id"],
        },
    )
    assert cross_project_report.status_code == 404
    checked(
        client.post(f"/api/v1/projects/{project_id}/jobs/{report['job_id']}/run", headers=headers)
    )
    downloaded = client.get(
        f"/api/v1/projects/{project_id}/reports/{report['resource_id']}/download",
        headers=headers,
    )
    assert downloaded.status_code == 200 and downloaded.content.startswith(b"PK")

    checked(client.get(f"/api/v1/projects/{project_id}/audit-logs", headers=headers))
    checked(client.get(f"/api/v1/projects/{project_id}/jobs", headers=headers))
