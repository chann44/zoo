# Auth API TODO
# 1. router
# 2. Handler
# 3. Logger
# 4. DB
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from logger.logger import logger
from utils.hash import PaswwordUtils
from db.generated.query import Querier, CreateUserParams
from db.generated.models import User
from db.connection import db_manager

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(hours=24)


class AuthRequst(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  
    name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    avatar_url: str | None


class AuthApi:
    def __init__(self, app: FastAPI):
        self.logger = logger
        self.app = app
        self.secret = os.environ.get("JWT_SECRET")
        if not self.secret:
            raise RuntimeError("JWT_SECRET is not set")
        self._register_routes()

    def _register_routes(self):
        self.app.post("/auth/signup", response_model=TokenResponse, status_code=201)(self.register)
        self.app.post("/auth/login", response_model=TokenResponse)(self.login)

        @self.app.get("/auth/me", response_model=UserResponse)
        def me(user: User = Depends(self.current_user)) -> UserResponse:
            return UserResponse(id=user.id, email=user.email, name=user.name, avatar_url=user.avatar_url)

    def _create_token(self, user_id: str) -> TokenResponse:
        now = datetime.now(timezone.utc)
        claims = {"sub": user_id, "iat": now, "exp": now + ACCESS_TOKEN_TTL}
        token = jwt.encode(claims, self.secret, algorithm=JWT_ALGORITHM)
        return TokenResponse(access_token=token, user_id=user_id)

    def register(self, payload: AuthRequst, db: Querier = Depends(db_manager.get_client)) -> TokenResponse:
        email = payload.email.lower()
        if db.get_user_by_email(email=email):
            raise HTTPException(status_code=400, detail="user already exists with this email")

        hashed_pwd = PaswwordUtils.hash_pass(payload.password)
        new_user: User | None = db.create_user(
            CreateUserParams(
                id=str(uuid.uuid4()),
                email=email,
                name=payload.name,
                avatar_url=None,
                password=hashed_pwd,
            )
        )
        if new_user is None:
            raise HTTPException(status_code=500, detail="failed to create user")

        self.logger.info("user signed up", extra={"user_id": new_user.id})
        return self._create_token(new_user.id)

    def login(self, payload: AuthRequst, db: Querier = Depends(db_manager.get_client)) -> TokenResponse:
        user = db.get_user_by_email(email=payload.email.lower())
        if user is None or not PaswwordUtils.verify_pass(user.password, payload.password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")

        self.logger.info("user logged in", extra={"user_id": user.id})
        return self._create_token(user.id)

    def user_from_token(self, token: str, db: Querier) -> User | None:
        try:
            claims = jwt.decode(token, self.secret, algorithms=[JWT_ALGORITHM])
        except jwt.PyJWTError:
            return None
        return db.get_user(id=claims.get("sub"))

    def current_user(
        self,
        creds: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
        db: Querier = Depends(db_manager.get_client),
    ) -> User:
        user = self.user_from_token(creds.credentials, db)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user
