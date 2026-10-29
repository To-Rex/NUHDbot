"""Object store wiring: URL resolution per mode and the TorexPloy S3_S3_* variable aliases."""
from app.config import Settings, settings
from app.services import storage


def test_url_modes(monkeypatch):
    monkeypatch.setattr(settings, "s3_endpoint", "")
    assert storage.url("a.webp") == "/static/uploads/a.webp"
    assert storage.url(None) is None
    for k, v in {"s3_endpoint": "http://tibfiles:8333", "s3_bucket": "nuhd", "s3_access_key_id": "k", "s3_secret_access_key": "s", "s3_public_url": ""}.items():
        monkeypatch.setattr(settings, k, v)
    assert settings.s3_enabled and storage.url("a.webp") == "/media/a.webp"
    monkeypatch.setattr(settings, "s3_public_url", "https://files.example.com/")
    assert storage.url("a.webp") == "https://files.example.com/nuhd/uploads/a.webp"


def test_torexploy_connection_aliases(monkeypatch):
    for k in ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("S3_S3_ENDPOINT", "http://tibfiles:8333")
    monkeypatch.setenv("S3_S3_ACCESS_KEY_ID", "ployf9b99909pt0b")
    monkeypatch.setenv("S3_S3_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("S3_S3_BUCKET", "nuhd")
    s = Settings(_env_file=None)
    assert s.s3_endpoint == "http://tibfiles:8333" and s.s3_bucket == "nuhd" and s.s3_access_key_id == "ployf9b99909pt0b" and s.s3_enabled
    monkeypatch.setenv("S3_ENDPOINT", "http://explicit:9000")
    assert Settings(_env_file=None).s3_endpoint == "http://explicit:9000"  # explicit name wins over the alias
