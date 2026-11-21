"""Optional checklist item 8: `examples/petstore.py` against the public Petstore.

Needs no Azure, only the internet: skipped unless `DAZURE_LIVE_HTTP=1`
(`DAZURE_LIVE` does not turn it on). The public store is shared and
writable, so the test uses ids of its own, tolerates other people's pets
in the lists it reads, and deletes what it created. pydantic and the
example are loaded inside the fixture, so collecting this module needs
neither.
"""

from __future__ import annotations

import importlib
import random

import pytest

import dazure


@pytest.fixture(scope="module")
def ps():
    # examples/ is on pytest's `pythonpath` (pyproject.toml).
    return importlib.import_module("petstore")


@pytest.fixture
def unique_id() -> int:
    # Far above the ids the store's own sample data and Swagger UI users pick.
    return random.SystemRandom().randrange(10**15, 10**16)


def test_pet_and_order_lifecycle(ps, unique_id):
    from pydantic import HttpUrl

    name = f"dazure-live-{unique_id}"
    with ps.PetStoreClient() as store:
        created = store.add_pet(
            ps.PetCreate(
                id=unique_id,
                name=name,
                photo_urls=[HttpUrl("https://example.com/dazure.png")],
                tags=[ps.Tag(id=1, name="dazure")],
                status="pending",
            )
        )
        try:
            assert isinstance(created, ps.Pet)
            assert (created.id, created.name, created.status) == (unique_id, name, "pending")
            assert created.photo_urls == ["https://example.com/dazure.png"]
            assert store.get_pet(unique_id) == created

            try:
                pending = store.find_pets_by_status(["pending"])
            except dazure.ResponseParseError:
                # Someone else's malformed pet; ours must still be in the raw list.
                raw = store.fetch(
                    "/pet/findByStatus",
                    query={"status": "pending"},
                    headers={"Accept": "application/json"},
                )
                assert unique_id in [p.get("id") for p in raw]
            else:
                assert unique_id in [p.id for p in pending]

            sold = store.update_pet(created.model_copy(update={"status": "sold"}))
            assert sold.status == "sold"
            assert store.get_pet(unique_id).status == "sold"

            order = store.place_order(ps.OrderCreate(id=unique_id, pet_id=unique_id, quantity=1))
            try:
                assert (order.id, order.pet_id, order.quantity) == (unique_id, unique_id, 1)
                assert store.get_order(unique_id).pet_id == unique_id
            finally:
                store.delete_order(unique_id)
            with pytest.raises(ps.OrderNotFoundError) as err:
                store.get_order(unique_id)
            assert isinstance(err.value.__cause__, dazure.ApiError)
        finally:
            store.delete_pet(unique_id)

        with pytest.raises(ps.PetNotFoundError) as err:
            store.get_pet(unique_id)
        assert err.value.__cause__.response.status_code == 404
