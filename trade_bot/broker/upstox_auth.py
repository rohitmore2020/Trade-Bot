"""
Upstox API v2 OAuth 2.0 Authentication Helper.

Provides secure authorization URL generation, authorization code exchange,
and token validation for Upstox API v2.
Guarantees zero hardcoded credentials and token redaction in all logging.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Dict, Optional
import urllib.parse
import urllib.request
import json

from trade_bot.broker.upstox_models import redact_token
from trade_bot.domain.exceptions import AuthenticationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UpstoxAuthToken:
    """Immutable validated Upstox token container."""
    access_token: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    email: Optional[str] = None

    def __repr__(self) -> str:
        return f"UpstoxAuthToken(user_id={self.user_id}, access_token={redact_token(self.access_token)})"


class UpstoxOAuthHandler:
    """
    Handles OAuth 2.0 handshake and token management for Upstox API v2.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        redirect_uri: str,
        base_url: str = "https://api.upstox.com/v2",
    ) -> None:
        if not api_key:
            raise AuthenticationError("Upstox api_key cannot be empty.")
        self.api_key = api_key
        self.api_secret = api_secret
        self.redirect_uri = redirect_uri
        self.base_url = base_url.rstrip("/")

    def get_authorization_url(self, state: Optional[str] = None) -> str:
        """
        Generate login authorization dialog URL for the user to authenticate.
        """
        params = {
            "response_type": "code",
            "client_id": self.api_key,
            "redirect_uri": self.redirect_uri,
        }
        if state:
            params["state"] = state
        query_string = urllib.parse.urlencode(params)
        return f"{self.base_url}/login/authorization/dialog?{query_string}"

    def exchange_code_for_token(self, code: str, timeout: float = 10.0) -> UpstoxAuthToken:
        """
        Exchange one-time authorization code for an active access token.
        Endpoint: POST https://api.upstox.com/v2/login/authorization/token
        """
        if not code:
            raise AuthenticationError("Authorization code cannot be empty.")
        if not self.api_secret:
            raise AuthenticationError("api_secret is required for OAuth code exchange.")

        url = f"{self.base_url}/login/authorization/token"
        form_data = {
            "code": code,
            "client_id": self.api_key,
            "client_secret": self.api_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        encoded_data = urllib.parse.urlencode(form_data).encode("utf-8")

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        req = urllib.request.Request(url, data=encoded_data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status_code = resp.getcode()
                raw_body = resp.read().decode("utf-8")
                data = json.loads(raw_body)

                if status_code != 200 or data.get("status") == "error":
                    errors = data.get("errors", [])
                    msg = errors[0].get("message") if errors else "OAuth token exchange failed"
                    raise AuthenticationError(f"Upstox OAuth error ({status_code}): {msg}")

                token_data = data.get("data", data)
                access_token = token_data.get("access_token")
                if not access_token:
                    raise AuthenticationError("No access_token received from Upstox response.")

                logger.info(
                    "Successfully obtained Upstox access token for user %s (token: %s)",
                    token_data.get("user_id"),
                    redact_token(access_token),
                )
                return UpstoxAuthToken(
                    access_token=access_token,
                    user_id=token_data.get("user_id"),
                    user_name=token_data.get("user_name"),
                    email=token_data.get("email"),
                )
        except urllib.error.HTTPError as e:
            try:
                err_json = json.loads(e.read().decode("utf-8"))
                errors = err_json.get("errors", [])
                msg = errors[0].get("message") if errors else e.reason
            except Exception:
                msg = str(e)
            raise AuthenticationError(f"Upstox token exchange HTTP {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise AuthenticationError(f"Network error during Upstox token exchange: {e.reason}") from e
        except json.JSONDecodeError as e:
            raise AuthenticationError(f"Malformed JSON in Upstox token response: {e}") from e
