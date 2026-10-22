"""テスト全体の共通設定。"""
import pytest


@pytest.fixture(autouse=True)
def allow_test_hosts(monkeypatch):
    # テスト用クライアントは "testserver" や "test" というホスト名で API を呼ぶ。
    monkeypatch.setenv("YATA_ALLOWED_HOSTS", "127.0.0.1,localhost,::1,testserver,test")
