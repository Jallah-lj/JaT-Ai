from jat_api.main import create_app


def test_application_metadata() -> None:
    app = create_app()
    assert app.title == "JaT API"
    assert app.version == "0.1.0"
