# Partial stubs for pyright (design §8.1): msal ships no type information, so
# strict mode would see everything from it as unknown. Only the names dazure
# uses, and those azure-identity's typed signatures name, with msal 1.x's
# types as its source documents them. Type checking only; not packaged.
from collections.abc import Iterator
from typing import Any

class TokenCache:
    class CredentialType:
        ACCESS_TOKEN: str
        REFRESH_TOKEN: str
        ACCOUNT: str
        ID_TOKEN: str
        APP_METADATA: str

    def __init__(self) -> None: ...
    def search(
        self,
        credential_type: str,
        target: list[str] | None = None,
        query: dict[str, Any] | None = None,
        *,
        now: float | None = None,
    ) -> Iterator[dict[str, Any]]: ...

class SerializableTokenCache(TokenCache):
    has_state_changed: bool
    def deserialize(self, state: str | None) -> None: ...
    def serialize(self) -> str: ...

class ClientApplication:
    def __init__(
        self,
        client_id: str,
        client_credential: Any = None,
        authority: str | None = None,
        **kwargs: Any,
    ) -> None: ...
    def initiate_auth_code_flow(
        self,
        scopes: list[str],
        redirect_uri: str | None = None,
        state: str | None = None,
        prompt: str | None = None,
        login_hint: str | None = None,
        domain_hint: str | None = None,
        claims_challenge: str | None = None,
        max_age: int | None = None,
        response_mode: str | None = None,
    ) -> dict[str, Any]: ...
    def acquire_token_by_auth_code_flow(
        self,
        auth_code_flow: dict[str, Any],
        auth_response: dict[str, Any],
        scopes: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...
    def acquire_token_by_refresh_token(
        self, refresh_token: str, scopes: list[str], **kwargs: Any
    ) -> dict[str, Any]: ...

class PublicClientApplication(ClientApplication): ...

class ConfidentialClientApplication(ClientApplication):
    ATTEMPT_REGION_DISCOVERY: bool
