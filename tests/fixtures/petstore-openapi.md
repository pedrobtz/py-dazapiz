# `petstore-openapi.json`

The OpenAPI 3.0.4 document of the Swagger Petstore v3, the spec oracle of
`tests/test_petstore_example.py` for the models in `examples/petstore.py`
(design §8.1).

- Source: <https://petstore3.swagger.io/api/v3/openapi.json>, saved
  unchanged (17106 bytes, SHA-256
  `00441c05add60f28da55eb4563d3fb6bbda364ba8eb7b381e2e2c98613005c82`).
- Fetched: 2026-11-21. `info.version` is `1.0.27`.
- Licence: Apache License 2.0, as the document's own `info.license` states
  (`"name": "Apache 2.0"`, <https://www.apache.org/licenses/LICENSE-2.0.html>);
  the document comes from
  [swagger-api/swagger-petstore](https://github.com/swagger-api/swagger-petstore).
  It is a test fixture only: it is not in the sdist or the wheel.

To refresh it, download the URL again, update the size, hash, date and
version here, and rerun the tests: a change to the `Pet` or `Order`
schema shows up as a failing spec-oracle test.
