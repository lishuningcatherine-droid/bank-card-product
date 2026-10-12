# Example Bank fixtures (SYNTHETIC)

Every file here is a synthetic page for the **fictional** Example Bank (`examplebank.example`, a reserved
`.example` domain). None of these products, rates, fees, or offers exist. They are used to test the shared extractors,
the classifier, offer-qualifier parsing, and the end-to-end pipeline, and to drive E2E tests under `E2E_TEST_DATA=1`.

Real-bank fixtures must be verbatim official pages stored under `tests/fixtures/<bank_id>/` with a `RETRIEVED.txt`.
