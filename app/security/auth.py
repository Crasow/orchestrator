import os
import time
import hashlib
import secrets
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request, status
from jwt.exceptions import PyJWTError, ExpiredSignatureError
import jwt

logger = logging.getLogger("orchestrator.auth")


class AuthManager:
    def __init__(self):
        self._secret_key = self._get_or_create_secret_key()
        self._algorithm = "HS256"
        self._token_expire_minutes = int(os.environ.get("TOKEN_EXPIRE_MINUTES", "30"))
        self._failed_attempts: Dict[str, list] = {}
        self._max_attempts = int(os.environ.get("MAX_LOGIN_ATTEMPTS", "5"))
        self._lockout_duration = int(os.environ.get("LOCKOUT_DURATION_MINUTES", "15"))

    def _get_or_create_secret_key(self) -> str:
        """Get or create the JWT secret key."""
        key_file = os.environ.get("JWT_SECRET_FILE", "/app/secrets/jwt_secret.key")

        if os.path.exists(key_file):
            try:
                with open(key_file, "r") as f:
                    return f.read().strip()
            except Exception as e:
                logger.error(f"Failed to read JWT secret: {e}")

        # Generate new key
        secret_key = secrets.token_urlsafe(64)
        try:
            os.makedirs(os.path.dirname(key_file), exist_ok=True)
            with open(key_file, "w") as f:
                f.write(secret_key)
            os.chmod(key_file, 0o600)  # Owner only
            logger.info(f"Created new JWT secret at {key_file}")
        except Exception as e:
            logger.warning(f"Failed to save JWT secret: {e}")

        return secret_key

    def hash_password(self, password: str) -> str:
        """Hash a password with PBKDF2-SHA256."""
        salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 100000
        )
        return f"pbkdf2_sha256${salt}${password_hash.hex()}"

    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify a password against its hash."""
        try:
            algorithm, salt, hash_value = hashed.split("$")
            if algorithm != "pbkdf2_sha256":
                return False

            password_hash = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), 100000
            )
            return secrets.compare_digest(password_hash.hex(), hash_value)
        except Exception:
            return False

    def create_access_token(self, data: Dict[str, Any]) -> str:
        """Create a JWT access token."""
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=self._token_expire_minutes
        )
        to_encode.update({"exp": expire})

        encoded_jwt = jwt.encode(to_encode, self._secret_key, algorithm=self._algorithm)
        return encoded_jwt

    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
            return payload
        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
            )
        except PyJWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            )

    def is_account_locked(self, identifier: str) -> bool:
        """Check if account is locked due to failed attempts."""
        if identifier not in self._failed_attempts:
            return False

        attempts = self._failed_attempts[identifier]
        if len(attempts) >= self._max_attempts:
            last_attempt = attempts[-1]
            if time.time() - last_attempt < self._lockout_duration * 60:
                return True
            else:
                # Reset counter after lockout expires
                del self._failed_attempts[identifier]

        return False

    def record_failed_attempt(self, identifier: str):
        """Record a failed login attempt."""
        if identifier not in self._failed_attempts:
            self._failed_attempts[identifier] = []

        self._failed_attempts[identifier].append(time.time())
        logger.warning(
            f"Failed login attempt for {identifier}. Total: {len(self._failed_attempts[identifier])}"
        )

        # Prune old attempts
        cutoff_time = time.time() - self._lockout_duration * 60
        self._failed_attempts[identifier] = [
            attempt
            for attempt in self._failed_attempts[identifier]
            if attempt > cutoff_time
        ]

    def clear_failed_attempts(self, identifier: str):
        """Clear failed login attempts for an identifier."""
        if identifier in self._failed_attempts:
            del self._failed_attempts[identifier]

    def get_admin_credentials(self) -> Optional[tuple]:
        """Get admin credentials from application settings."""
        from app.config import settings

        username = settings.security.admin_username
        password_hash = settings.security.admin_password_hash

        if not username or not password_hash:
            logger.error("Admin credentials not configured (set SECURITY__ADMIN_USERNAME and SECURITY__ADMIN_PASSWORD_HASH)")
            return None

        return username, password_hash

    def authenticate_admin(
        self, username: str, password: str, client_ip: str
    ) -> Optional[str]:
        """Authenticate admin user and return a JWT token."""
        # Check lockout
        if self.is_account_locked(f"{username}@{client_ip}"):
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Account temporarily locked due to failed attempts",
            )

        credentials = self.get_admin_credentials()
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Admin authentication not configured",
            )

        admin_username, password_hash = credentials

        if username != admin_username:
            self.record_failed_attempt(f"{username}@{client_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        if not self.verify_password(password, password_hash):
            self.record_failed_attempt(f"{username}@{client_ip}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        # Successful authentication
        self.clear_failed_attempts(f"{username}@{client_ip}")

        # Create token
        token = self.create_access_token(
            {
                "sub": username,
                "role": "admin",
                "ip": client_ip,
                "iat": int(datetime.now(timezone.utc).timestamp()),
            }
        )

        logger.info(f"Admin {username} authenticated successfully from {client_ip}")
        return token

    def _extract_token(self, request: Request) -> str:
        """Extract JWT token from cookie first, then from Authorization header."""
        # 1. Cookie
        token = request.cookies.get("access_token")
        if token:
            return token

        # 2. Authorization: Bearer <token>
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    async def verify_admin_token(self, request: Request) -> Dict[str, Any]:
        """Verify admin token from cookie or header."""
        try:
            token = self._extract_token(request)
            payload = self.verify_token(token)

            if payload.get("role") != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin access required",
                )

            client_ip = request.client.host if request.client else "unknown"
            token_ip = payload.get("ip")
            if token_ip and token_ip != client_ip:
                logger.warning(f"Token IP mismatch: {token_ip} vs {client_ip}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token validation failed",
                )

            return payload

        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )


# Global singleton
auth_manager = AuthManager()


async def get_current_admin(request: Request):
    """FastAPI dependency that verifies admin authentication."""
    return await auth_manager.verify_admin_token(request)
