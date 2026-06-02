"""Unit tests for authentication service."""
import pytest
from fastapi import HTTPException

from app.services.auth_service import AuthService, hash_password, verify_password
from app.schemas.schemas import CustomerCreate


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("MySecret99")
        assert verify_password("MySecret99", hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False


@pytest.mark.asyncio
class TestAuthService:
    async def test_register_new_customer(self, db_session):
        service = AuthService(db_session)
        customer = await service.register(CustomerCreate(
            name="Bob Jones",
            email="bob@example.com",
            password="Secure1234",
        ))
        assert customer.id is not None
        assert customer.email == "bob@example.com"
        assert "Secure1234" not in customer.password_hash  # hashed

    async def test_register_duplicate_email_raises(self, db_session):
        service = AuthService(db_session)
        payload = CustomerCreate(name="Alice", email="alice@example.com", password="Secure1234")
        await service.register(payload)
        with pytest.raises(HTTPException) as exc_info:
            await service.register(payload)
        assert exc_info.value.status_code == 409

    async def test_login_returns_token(self, db_session):
        service = AuthService(db_session)
        await service.register(CustomerCreate(name="Carol", email="carol@example.com", password="Secure1234"))
        token = await service.login("carol@example.com", "Secure1234")
        assert isinstance(token, str)
        assert len(token) > 20

    async def test_login_wrong_password_raises(self, db_session):
        service = AuthService(db_session)
        await service.register(CustomerCreate(name="Dave", email="dave@example.com", password="Secure1234"))
        with pytest.raises(HTTPException) as exc_info:
            await service.login("dave@example.com", "WrongPassword")
        assert exc_info.value.status_code == 401

    async def test_login_unknown_email_raises(self, db_session):
        service = AuthService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await service.login("nobody@example.com", "anything")
        assert exc_info.value.status_code == 401
