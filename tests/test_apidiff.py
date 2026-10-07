import unittest

from services.apidiff import (
    ChangeType,
    diff_surfaces,
    extract_openapi,
    extract_python_module,
    extract_typescript,
    to_change_record,
)
from services.hearth_agent.models import ChangeKind, PackageRef

OLD_SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/v1/charges": {"post": {"operationId": "createCharge", "requestBody": {"content": {"application/json": {
            "schema": {"type": "object", "required": ["amount"], "properties": {
                "amount": {"type": "integer"}, "source": {"type": "string"}}}}}},
            "responses": {"200": {"description": "ok"}}}},
        "/v1/customers/{id}": {"get": {"parameters": [{"name": "id", "in": "path", "schema": {"type": "string"}}],
                                       "responses": {"200": {"description": "ok"}}}},
    },
    "components": {"schemas": {"Customer": {"type": "object", "required": ["id"], "properties": {
        "id": {"type": "string"}, "email": {"type": "string"}}}}},
}

NEW_SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/v1/customers/{customer}": {"get": {
            "deprecated": True,
            "parameters": [{"name": "customer", "in": "path", "schema": {"type": "string"}},
                           {"name": "expand", "in": "query", "required": True, "schema": {"type": "string"}}],
            "responses": {"200": {"description": "ok"}}}},
        "/v1/payment_intents": {"post": {"operationId": "createPaymentIntent",
                                         "responses": {"200": {"description": "ok"}}}},
    },
    "components": {"schemas": {"Customer": {"type": "object", "required": ["id"], "properties": {
        "id": {"type": "integer"}}}}},
}


def _types(changes):
    return {(c.type, c.symbol) for c in changes}


class OpenApiDiffTests(unittest.TestCase):
    def test_diff(self):
        t = _types(diff_surfaces(extract_openapi(OLD_SPEC), extract_openapi(NEW_SPEC)))
        self.assertIn((ChangeType.REMOVED, "POST /v1/charges"), t)
        self.assertIn((ChangeType.ADDED, "POST /v1/payment_intents"), t)
        # a renamed path variable ({id} -> {customer}) is the same operation, not a removal
        self.assertIn((ChangeType.DEPRECATED, "GET /v1/customers/{}"), t)
        self.assertIn((ChangeType.PARAM_ADDED_REQUIRED, "GET /v1/customers/{}"), t)
        self.assertIn((ChangeType.FIELD_REMOVED, "schema:Customer"), t)
        self.assertIn((ChangeType.FIELD_TYPE_CHANGED, "schema:Customer"), t)

    def test_yaml_text(self):
        surface = extract_openapi("openapi: 3.0.0\npaths:\n  /x:\n    get:\n      responses: {}\n")
        self.assertIn("GET /x", surface.symbols)

    def test_change_record_folding(self):
        changes = diff_surfaces(extract_openapi(OLD_SPEC), extract_openapi(NEW_SPEC))
        cr = to_change_record(changes, provider="stripe",
                              package=PackageRef(ecosystem="npm", name="stripe", **{"from": "16", "to": "17"}))
        self.assertIsNotNone(cr)
        self.assertEqual(cr.kind, ChangeKind.BREAKING)
        self.assertTrue(cr.id.startswith("cr_") and cr.symbols)
        self.assertIsNone(to_change_record([], provider="x", package=PackageRef(ecosystem="npm", name="x")))


class PythonDiffTests(unittest.TestCase):
    def test_diff_and_rename(self):
        old = '''
__all__ = ["Client", "create_charge"]
def create_charge(amount: int, source: str, *, idempotency_key=None) -> dict: ...
class Client:
    timeout: float
    def list_customers(self, limit: int = 10) -> list: ...
    def get(self, id: str) -> dict: ...
'''
        new = '''
__all__ = ["Client"]
class Client:
    timeout: float
    def list_customers(self, limit: int, starting_after: str | None = None) -> list: ...
    def retrieve(self, id: str) -> dict: ...
'''
        changes = diff_surfaces(extract_python_module(old, "sdk"), extract_python_module(new, "sdk"))
        t = _types(changes)
        self.assertIn((ChangeType.REMOVED, "sdk.create_charge"), t)
        self.assertIn((ChangeType.PARAM_BECAME_REQUIRED, "sdk.Client.list_customers"), t)
        self.assertIn((ChangeType.PARAM_ADDED_OPTIONAL, "sdk.Client.list_customers"), t)
        renamed = [c for c in changes if c.type == ChangeType.RENAMED]
        self.assertEqual([(c.symbol, c.renamed_to) for c in renamed], [("sdk.Client.get", "sdk.Client.retrieve")])


class TypeScriptDiffTests(unittest.TestCase):
    def test_diff(self):
        old = '''
export declare class Charges {
  create(params: ChargeCreateParams, options?: RequestOptions): Promise<Charge>;
  list(params?: ListParams): Promise<Charge[]>;
}
export interface ChargeCreateParams { amount: number; currency: string; source?: string; }
export declare function constructEvent(payload: string, header: string, secret: string): Event;
export type Mode = "live" | "test";
'''
        new = '''
export declare class Charges {
  /** @deprecated use paymentIntents */
  list(params?: ListParams): Promise<Charge[]>;
}
export interface ChargeCreateParams { amount: number; currency: string; payment_method: string; }
export declare function constructEvent(payload: string | Buffer, header: string, secret: string): Event;
export type Mode = "live" | "test" | "sandbox";
'''
        changes = diff_surfaces(extract_typescript(old, "Stripe"), extract_typescript(new, "Stripe"))
        t = _types(changes)
        self.assertIn((ChangeType.REMOVED, "Stripe.Charges.create"), t)
        self.assertIn((ChangeType.DEPRECATED, "Stripe.Charges.list"), t)
        self.assertIn((ChangeType.FIELD_REMOVED, "Stripe.ChargeCreateParams"), t)
        self.assertIn((ChangeType.FIELD_ADDED_REQUIRED, "Stripe.ChargeCreateParams"), t)
        self.assertIn((ChangeType.PARAM_TYPE_CHANGED, "Stripe.constructEvent"), t)
        self.assertIn((ChangeType.FIELD_TYPE_CHANGED, "Stripe.Mode"), t)
        self.assertTrue(all(c.confidence < 1 for c in changes))  # heuristic scanner never claims certainty


if __name__ == "__main__":
    unittest.main()
