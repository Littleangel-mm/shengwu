from app.services.report import ReportService


def test_word_evidence_truncation_notice_is_explicit() -> None:
    notice = ReportService._evidence_truncation_notice()
    assert "超过 1000 条" in notice
    assert "仅展示前 1000 条" in notice
    assert "完整证据" in notice
