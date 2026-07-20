from app.services.prisma import PrismaService


def test_normalize_coerces_and_floors_counts() -> None:
    data = PrismaService._normalize(
        {
            "identified_databases": "12",
            "records_screened": -5,
            "studies_included": 3.9,
            "unknown_field": 99,
        }
    )
    assert data["identified_databases"] == 12
    assert data["records_screened"] == 0
    assert data["studies_included"] == 3
    assert "unknown_field" not in data
    assert data["reports_excluded"] == []


def test_normalize_keeps_valid_exclusion_reasons() -> None:
    data = PrismaService._normalize(
        {
            "reports_excluded": [
                {"reason": "综述类文献", "count": 4},
                {"reason": "", "count": 2},
                {"reason": "无对照组", "count": "bad"},
            ]
        }
    )
    reasons = data["reports_excluded"]
    assert len(reasons) == 2
    assert reasons[0] == {"reason": "综述类文献", "count": 4}
    assert reasons[1] == {"reason": "无对照组", "count": 0}


def test_render_diagram_returns_png_bytes() -> None:
    png = PrismaService.render_diagram(PrismaService._normalize({"studies_included": 8}))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 1000
