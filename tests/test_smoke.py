import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough")
os.environ.setdefault("DB_NAME", "smartbill_test")
os.environ.setdefault("DB_USER", "test")
from app import create_app

def test_home_page_loads():
    app=create_app()
    app.config.update(TESTING=True)
    client=app.test_client()
    response=client.get("/")
    assert response.status_code == 200
