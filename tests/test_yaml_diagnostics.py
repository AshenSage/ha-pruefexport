"""Malformed source YAML must stay private while its location is reviewable."""
import json
import unittest

import test_export


class YAMLDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_export.ExportTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_parser_coordinates_without_secret_or_source_snippet(self):
        secret = "synthetic_private_value_12345"
        self.fixture.write("secrets.yaml", "api_key: " + secret + "\n")
        self.fixture.write("custom_components/example/services.yaml",
                           "fetch:\n  name: Public action\n  description: " + secret + ": invalid\n")
        _, result, files = self.fixture.build()
        inventory = json.loads(files["inventar/dateien.json"])
        row = next(item for item in inventory if item["pfad"] == "custom_components/example/services.yaml")
        self.assertEqual(result["status"], "teilweise")
        self.assertEqual(row["fehlerart"], "ScannerError")
        self.assertEqual(row["yaml_zeile"], 3)
        self.assertGreater(row["yaml_spalte"], 0)
        self.assertIn("Zeile 3", files["EXPORTBERICHT.md"].decode())
        self.assertNotIn("erweiterungen/custom_components/example/services.yaml", files)
        self.assertNotIn(secret.encode(), b"\n".join(files.values()))
        self.assertNotIn(b"description:", files["EXPORTBERICHT.md"])
        self.assertIn("konfiguration/automations.yaml", files)

    def test_quoted_colon_is_valid_and_still_exported(self):
        self.fixture.write("custom_components/example/services.yaml",
                           'fetch:\n  description: "Public action: valid description"\n')
        _, result, files = self.fixture.build()
        self.assertEqual(result["status"], "vollstaendig")
        self.assertIn("erweiterungen/custom_components/example/services.yaml", files)


if __name__ == "__main__":
    unittest.main()
