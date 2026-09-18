import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.interpreter import InterpretationError
from main import app
from app.schemas import Directive


def request_payload():
    return {
        "scenario_id": "contract-test",
        "operator_notes": [
            "Solar output will drop to 20% from 1 PM to 3 PM.",
            "The cafeteria menu changes tomorrow.",
        ],
        "hours": [
            {
                "hour": hour,
                "demand_kwh": 100,
                "solar_kwh": 50 if hour in {13, 14} else 0,
                "tariff_bdt_per_kwh": 10 + hour,
            }
            for hour in range(24)
        ],
        "battery": {
            "capacity_kwh": 100,
            "initial_energy_kwh": 50,
            "minimum_energy_kwh": 0,
            "max_charge_kwh_per_hour": 25,
            "max_discharge_kwh_per_hour": 25,
        },
    }


class GridWiseContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_index_renders_dashboard(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("GridWise", response.text)

    def test_optimization_applies_validated_directives(self):
        directives = [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
                "explanation": "Only 20 percent of solar remains.",
            },
            {
                "note_index": 1,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "This note does not affect energy scheduling.",
            },
        ]
        with patch(
            "main.interpret_notes",
            return_value=[Directive.model_validate(item) for item in directives],
        ):
            response = self.client.post("/optimize-energy", json=request_payload())

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["scenario_id"], "contract-test")
        self.assertEqual(len(body["directive_interpretation"]), 2)
        self.assertTrue(all("explanation" in item for item in body["directive_interpretation"]))
        self.assertLessEqual(body["hourly_plan"][13]["solar_used_kwh"], 10.01)
        self.assertLessEqual(body["hourly_plan"][14]["solar_used_kwh"], 10.01)

    def test_malformed_request_is_rejected(self):
        payload = request_payload()
        payload["hours"] = payload["hours"][:-1]
        response = self.client.post("/optimize-energy", json=payload)
        self.assertEqual(response.status_code, 422)

    def test_llm_failure_is_controlled(self):
        with patch(
            "main.interpret_notes",
            side_effect=InterpretationError("provider timeout"),
        ):
            response = self.client.post("/optimize-energy", json=request_payload())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"], "Operator-note interpretation unavailable"
        )


if __name__ == "__main__":
    unittest.main()
