"""The Petstore client as if the Petstore were an Azure-hosted API.

The public Swagger Petstore is open: it needs no token, which is why
`PetStoreClient` has no credential. A real API you put behind Entra ID
needs one, and this subclass shows the three class attributes that add it:
the API's token scope and the variables holding its service principal.
`app_credential()` then picks the service principal when both are set, else
your `az login` (design §4.1.1).

Its tests, in `examples/tests/`, are the pattern the guide page "Testing
your API client" walks through: HTTP mocked with `respx`, the credential
faked with `dazapiz.testing.StaticTokenCredential`, no Azure and no network.
Pointed at the public store it still works, since the store ignores the
`Authorization` header, but it needs a credential to get a token first.
"""

from __future__ import annotations

from petstore import PetStoreClient

__all__ = ["AzurePetStoreClient"]


class AzurePetStoreClient(PetStoreClient):
    """The Petstore client with Entra ID authentication, for the testing guide.

    Every method is `PetStoreClient`'s; only where the token comes from is new.
    """

    scope = "api://00000000-0000-0000-0000-000000000000/.default"
    client_id_env = "PETSTORE_CLIENT_ID"
    client_secret_env = "PETSTORE_CLIENT_SECRET"
