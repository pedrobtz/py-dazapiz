"""A typed client for the Swagger Petstore v3, on `dazapiz.ApiClient`.

An example of an `ApiClient` subclass with validated request bodies and
responses (design §4.1, D53). Run it against the public Petstore with::

    uv run python examples/petstore.py

It needs pydantic (in the dev group), not Azure: the Petstore is open, so
the client has no credential. The models follow the store's OpenAPI
document (`tests/fixtures/petstore-openapi.json`, checked by
`tests/test_petstore_example.py`):

- camelCase on the wire, snake_case in Python (`alias_generator=to_camel`),
  either accepted when validating;
- frozen, so a validated object cannot be changed behind the check;
- separate request and response models: a request refuses unknown fields
  (`extra="forbid"`, a typo fails before anything is sent); a response
  ignores them (`extra="ignore"`, a server that adds a field does not break
  the client), but a missing required field, an unknown status or a bad
  photo URL fails, as `dazapiz.ResponseParseError`;
- request models are sent with only the fields that were set
  (`fetch(json=model)` dumps with `exclude_unset=True`), so an optional
  field left out is not sent as `null`.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter
from pydantic.alias_generators import to_camel

from dazapiz import ApiClient, ApiError

__all__ = [
    "Category",
    "Order",
    "OrderCreate",
    "OrderNotFoundError",
    "OrderStatus",
    "Pet",
    "PetCreate",
    "PetNotFoundError",
    "PetStatus",
    "PetStoreClient",
    "Tag",
]

PETSTORE_URL = "https://petstore3.swagger.io/api/v3"

PetStatus = Literal["available", "pending", "sold"]
OrderStatus = Literal["placed", "approved", "delivered"]

# The schema's ids are int64; Petstore ids are never negative.
Id = Annotated[int, Field(ge=0, le=2**63 - 1)]


class _Model(BaseModel):
    """camelCase aliases, validated by alias or by name, immutable."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        frozen=True,
    )


class _Request(_Model):
    """A request body: an unknown field is an error, before anything is sent."""

    model_config = ConfigDict(extra="forbid")


class _Response(_Model):
    """A response body: unknown fields are ignored, the rest is validated."""

    model_config = ConfigDict(extra="ignore")


class Category(_Response):
    """A pet's category. Shared by requests and responses, so it ignores extras."""

    id: Id | None = None
    name: str | None = None


class Tag(_Response):
    """A tag on a pet. Shared by requests and responses, so it ignores extras."""

    id: Id | None = None
    name: str | None = None


class PetCreate(_Request):
    """A pet to add. The store requires `name` and `photo_urls`, which must be URLs.

    The schema leaves `id` optional, but the public store answers 500 to a
    pet without one (2026-11-21), so pass your own.
    """

    id: Id | None = None
    name: Annotated[str, Field(min_length=1)]
    photo_urls: list[HttpUrl]
    category: Category | None = None
    tags: list[Tag] | None = None
    status: PetStatus | None = None


class Pet(_Response):
    """A pet as the store returns it: always with its `id`.

    `photo_urls` are strings, as the schema types them (no `format: uri`):
    the public store holds pets whose photo URL is `"string"`, and a
    response is checked against the API's contract, not a stricter one.
    `PetCreate` checks the URLs it sends.
    """

    id: Id
    name: str
    photo_urls: list[str]
    category: Category | None = None
    tags: list[Tag] | None = None
    status: PetStatus | None = None


class OrderCreate(_Request):
    """An order to place, for `quantity` of the pet `pet_id`."""

    id: Id | None = None
    pet_id: Id
    quantity: Annotated[int, Field(ge=1, le=2**31 - 1)]
    ship_date: datetime | None = None
    status: OrderStatus | None = None
    complete: bool | None = None


class Order(_Response):
    """An order as the store returns it: always with its `id`."""

    id: Id
    pet_id: Id | None = None
    quantity: int | None = None
    ship_date: datetime | None = None
    status: OrderStatus | None = None
    complete: bool | None = None


# The store answers XML unless asked for JSON.
_JSON = {"Accept": "application/json"}

# Built once: a TypeAdapter compiles its validator when it is created.
_PETS = TypeAdapter(list[Pet])
_STATUSES = TypeAdapter(tuple[PetStatus, ...])


class PetNotFoundError(LookupError):
    """No pet with that id; `__cause__` is the store's 404 `dazapiz.ApiError`."""


class OrderNotFoundError(LookupError):
    """No order with that id; `__cause__` is the store's 404 `dazapiz.ApiError`."""


class PetStoreClient(ApiClient):
    """The Swagger Petstore v3 pet and store operations, typed and validated.

    Requests go unauthenticated (no credential: the store is open). Every
    method sends a validated model and returns one, so a malformed response
    raises `dazapiz.ResponseParseError` (its `__cause__` is pydantic's
    `ValidationError`) rather than returning a half-checked dict.

    Examples
    --------
    >>> with PetStoreClient() as store:  # doctest: +SKIP
    ...     pets = store.find_pets_by_status(["available"])
    """

    host_url = PETSTORE_URL

    def add_pet(self, pet: PetCreate) -> Pet:
        """Add a pet to the store.

        Parameters
        ----------
        pet : PetCreate
            The pet to add.

        Returns
        -------
        Pet
            The pet as stored, validated.
        """
        return self.fetch("/pet", "POST", json=pet, headers=_JSON, parse=Pet.model_validate)

    def get_pet(self, pet_id: int) -> Pet:
        """Find a pet by id.

        Parameters
        ----------
        pet_id : int
            The pet's id.

        Returns
        -------
        Pet

        Raises
        ------
        PetNotFoundError
            The store has no such pet (HTTP 404), chained to the `ApiError`.
        """
        try:
            return self.fetch(
                "/pet/{pet_id}", headers=_JSON, parse=Pet.model_validate, pet_id=str(pet_id)
            )
        except ApiError as err:
            if err.response.status_code == 404:
                raise PetNotFoundError(f"No pet with id {pet_id}.") from err
            raise

    def find_pets_by_status(self, status: Sequence[PetStatus]) -> list[Pet]:
        """Find the pets with any of the given statuses.

        Parameters
        ----------
        status : sequence of {"available", "pending", "sold"}
            At least one status. The store's `status` parameter takes one
            value (a second is ignored, a comma-separated list refused), so
            each distinct status is one request, in the order given.

        Returns
        -------
        list of Pet
            The pets of each status in turn, each validated: one malformed
            pet fails the whole call.

        Raises
        ------
        TypeError
            `status` is a single string rather than a sequence of them.
        ValueError
            `status` is empty.
        pydantic.ValidationError
            A status is not one of the three; nothing is sent.
        """
        if isinstance(status, str):
            raise TypeError('status is a sequence of statuses: pass ["sold"], not "sold".')
        statuses = _STATUSES.validate_python(tuple(status))
        if not statuses:
            raise ValueError("Pass at least one status.")
        pets: list[Pet] = []
        for one in dict.fromkeys(statuses):
            pets += self.fetch(
                "/pet/findByStatus",
                query={"status": one},
                headers=_JSON,
                parse=_PETS.validate_python,
            )
        return pets

    def update_pet(self, pet: Pet) -> Pet:
        """Replace a stored pet, found by `pet.id`, with `pet`.

        Parameters
        ----------
        pet : Pet
            The pet with its new values, such as
            ``pet.model_copy(update={"status": "sold"})``.

        Returns
        -------
        Pet
            The pet as stored, validated.
        """
        return self.fetch("/pet", "PUT", json=pet, headers=_JSON, parse=Pet.model_validate)

    def delete_pet(self, pet_id: int) -> None:
        """Delete a pet.

        Parameters
        ----------
        pet_id : int
            The pet's id.
        """
        # The store labels its plain-text reply ("Pet deleted") as JSON, which would
        # not parse (ResponseParseError): read it as the text it is.
        self.fetch(
            "/pet/{pet_id}", "DELETE", headers=_JSON, content_type="text/plain", pet_id=str(pet_id)
        )

    def place_order(self, order: OrderCreate) -> Order:
        """Place an order for a pet.

        Parameters
        ----------
        order : OrderCreate

        Returns
        -------
        Order
            The order as stored, validated.
        """
        return self.fetch(
            "/store/order", "POST", json=order, headers=_JSON, parse=Order.model_validate
        )

    def get_order(self, order_id: int) -> Order:
        """Find a purchase order by id.

        Parameters
        ----------
        order_id : int

        Returns
        -------
        Order

        Raises
        ------
        OrderNotFoundError
            The store has no such order (HTTP 404), chained to the `ApiError`.
        """
        try:
            return self.fetch(
                "/store/order/{order_id}",
                headers=_JSON,
                parse=Order.model_validate,
                order_id=str(order_id),
            )
        except ApiError as err:
            if err.response.status_code == 404:
                raise OrderNotFoundError(f"No order with id {order_id}.") from err
            raise

    def delete_order(self, order_id: int) -> None:
        """Delete a purchase order.

        Parameters
        ----------
        order_id : int
        """
        self.fetch(
            "/store/order/{order_id}",
            "DELETE",
            headers=_JSON,
            content_type="text/plain",
            order_id=str(order_id),
        )


def main() -> None:
    """Add a pet, find it, sell it, order it and delete it, on the public store."""
    # The public store is shared: an id of our own, high enough to avoid others'.
    pet_id = random.randrange(10**12, 10**13)
    with PetStoreClient(verbose=True) as store:
        pet = store.add_pet(
            PetCreate(
                id=pet_id,
                name="dazapiz-example",
                photo_urls=[HttpUrl("https://example.com/dazapiz.png")],
                tags=[Tag(id=1, name="dazapiz")],
                status="available",
            )
        )
        print(f"Added {pet!r}")
        try:
            print(f"Found {store.get_pet(pet.id)!r}")
            sold = store.update_pet(pet.model_copy(update={"status": "sold"}))
            print(f"Updated to {sold.status}")
            order = store.place_order(OrderCreate(id=pet_id, pet_id=pet.id, quantity=1))
            print(f"Placed {order!r}")
            store.delete_order(order.id)
        finally:
            store.delete_pet(pet.id)
        try:
            store.get_pet(pet.id)
        except PetNotFoundError as err:
            print(f"Deleted: {err}")


if __name__ == "__main__":
    main()
