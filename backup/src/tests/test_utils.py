from app.services.utils import make_slug


def test_make_slug_supports_unicode() -> None:
    assert make_slug("通用 科研 项目", 120) == "通用-科研-项目"
