"""Credential regressions use invented values only, including python-kasa's shape."""
import base64
import json
import unittest
from urllib.parse import quote

import yaml

import test_export
from ha_pruefexport.exporter import MAX_CREDENTIAL_PAYLOAD, Redactor, credential_payload, is_secret_key


class CredentialRedactionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_export.ExportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_credential_name_variants_mask_opaque_values(self):
        for name in ("credentials_hash", "credentialsHash", "CREDENTIALS_HASH",
                     "credential_blob", "mqtt_credentials_base64", "password_hash",
                     "passwordHash", "pwd", "pass", "clientSecretData", "apiKeyHash",
                     "APIKeyHash", "session_cookie", "cookieJar", "secretData",
                     "refreshTokenHash", "authorization_header", "authData", "httpAuth",
                     "privateKeyHash", "sessionIdHash", "vendor.credentials.hash",
                     "accessKeyId", "pin_hash", "passcodeData", "accessCodeHash"):
            with self.subTest(name=name):
                self.assertTrue(is_secret_key(name))
                redactor = Redactor()
                value = {name: "synthetic_opaque_value_123"}
                redactor.learn(value)
                self.assertEqual(redactor.object(value)[name], "[MASKIERT]")

    def test_public_fields_and_templates_remain_readable(self):
        public = {"error_code": 200, "supported_features": 32, "keyboard": "qwerty",
                  "passive": False, "bypass": True, "tokenizer": "public"}
        for name in public:
            self.assertFalse(is_secret_key(name), name)
        template = "{{ states('input_text.private') }}"
        value = {**public, "password": template}
        redactor = Redactor()
        redactor.learn(value)
        self.assertEqual(redactor.object(value), value)

    def test_kasa_envelope_removed_from_storage_runtime_and_duplicates_in_real_zip(self):
        username = "synthetic-user@example.invalid"
        password = "synthetic_password_42!"
        encoded = base64.b64encode(json.dumps({"un": username, "pwd": password}).encode()).decode()
        entries = [{"domain": "tplink", "data": {"credentials_hash": encoded,
                    "model": "Synthetic camera", "host": "192.0.2.1"}}]
        storage = {"version": 1, "minor_version": 1, "key": "core.config_entries",
                   "data": {"entries": entries}}
        self.fixture.write(".storage/core.config_entries", json.dumps(storage))
        self.fixture.write("notes.txt", "Copied envelope: " + encoded + "\nUser: " + username +
                           "\nPassword copy: " + password + "\n")
        self.fixture.snapshot["files"]["inventar/integrationen.json"] = entries
        _, _, files = self.fixture.build()
        combined = b"\n".join(files.values()).decode()
        for private in (encoded, username, password):
            self.assertNotIn(private, combined)
        for name in ("konfiguration/.storage/core.config_entries", "inventar/integrationen.json"):
            payload = json.loads(files[name])
            row = payload["data"]["entries"][0] if isinstance(payload, dict) else payload[0]
            self.assertEqual(row["data"]["credentials_hash"], "[MASKIERT]")
            self.assertEqual(row["data"]["host"], "192.0.2.1")

    def test_sensitive_containers_and_their_duplicated_leaves_are_masked(self):
        payload = {"credentials": {"user": "synthetic_user_123", "values": ["nested_value_456"]},
                   "tokens": ["synthetic_token_789"], "access_token": ["synthetic_access_246"]}
        self.fixture.snapshot["files"]["runtime/private.json"] = payload
        self.fixture.write("copies.json", json.dumps({"copy": "nested_value_456"}))
        _, _, files = self.fixture.build()
        result = json.loads(files["runtime/private.json"])
        self.assertEqual(result, {"credentials": "[MASKIERT]", "tokens": "[MASKIERT]", "access_token": "[MASKIERT]"})
        for value in (b"synthetic_user_123", b"nested_value_456", b"synthetic_token_789", b"synthetic_access_246"):
            self.assertNotIn(value, b"\n".join(files.values()))

    def test_yaml_collections_aliases_and_tagged_secrets_stay_valid(self):
        self.fixture.write("configuration.yaml", "credentials: &login\n  user: synthetic_yaml_user\n"
                           "  values: [synthetic_yaml_pass]\ncopy: *login\n"
                           "api_key: !secret local_api\npublic: 17\n")
        self.fixture.write("secrets.yaml", "local_api: synthetic_local_api\n")
        _, _, files = self.fixture.build()
        output = files["konfiguration/configuration.yaml"].decode()
        root = yaml.compose(output)
        self.assertIsNotNone(root)
        self.assertIn("!secret local_api", output)
        self.assertIn("public: 17", output)
        self.assertNotIn("synthetic_yaml", output)

    def test_payload_detection_handles_json_base64_urlsafe_and_percent_encoding(self):
        payload = {"un": "synthetic_name_123", "pwd": "synthetic_pass_ä_456"}
        raw = json.dumps(payload, ensure_ascii=False)
        standard = base64.b64encode(raw.encode()).decode()
        urlsafe = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
        for value in (raw, standard, urlsafe, quote(standard, safe="")):
            with self.subTest(kind=value[:8]):
                self.assertEqual(credential_payload(value), payload)
                redactor = Redactor()
                redactor.learn({"provider_data": value})
                self.assertEqual(redactor.object({"provider_data": value})["provider_data"], "[MASKIERT]")
                self.assertNotIn(payload["pwd"], redactor.text("copy=" + payload["pwd"]))

    def test_basic_auth_header_is_masked_and_decoded_values_are_learned(self):
        username, password = "synthetic_basic_user", "synthetic_basic_pass"
        value = "Basic " + base64.b64encode((username + ":" + password).encode()).decode()
        redactor = Redactor()
        redactor.learn({"header_copy": value})
        self.assertEqual(redactor.object({"header_copy": value})["header_copy"], "[MASKIERT]")
        self.assertNotIn(password, redactor.text(password))
        self.assertNotIn(username, redactor.text(username))
        self.assertNotIn(value[6:], redactor.text("copy=" + value[6:]))

    def test_public_encoded_json_and_malformed_or_oversized_values_are_not_decoded(self):
        public = base64.b64encode(b'{"temperature": 23, "enabled": true}').decode()
        for value in (public, "not*base64", "Basic invalid", "a" * (MAX_CREDENTIAL_PAYLOAD + 1),
                      base64.b64encode(b'\xff\xfe').decode(), '"public JSON string"'):
            with self.subTest(size=len(value)):
                self.assertIsNone(credential_payload(value))
        redactor = Redactor()
        self.assertEqual(redactor.object({"public_data": public}), {"public_data": public})
        # Even an oversized/malformed value is masked when its field is sensitive.
        self.assertEqual(redactor.object({"credentials_hash": "not*base64"}),
                         {"credentials_hash": "[MASKIERT]"})

    def test_script_shell_and_log_fields_use_the_same_name_rules(self):
        self.fixture.write("local.py", 'credentials_hash = "synthetic_script_123"\n'
                           'apiKeyHash = "synthetic_api_456"\npublic = "preserve_me"\n'
                           'key = "public_method_name"\n')
        self.fixture.write("local.sh", "export CREDENTIALS_HASH=synthetic_shell_789!\n"
                           "PASSWORD=$EXISTING_VALUE\nPUBLIC=value\n")
        self.fixture.write("home-assistant.log", "integration warning pwd=synthetic_file_log_789! "
                           "credentialsHash=synthetic_file_hash_246 public=17\n")
        self.fixture.snapshot["files"]["diagnose/system_log.json"] = {"entries": [{
            "message": ['credentials_hash="synthetic_log_123" pwd=synthetic_log_pass_456! public=17']}]}
        _, _, files = self.fixture.build()
        combined = b"\n".join(files.values())
        for value in (b"synthetic_script_123", b"synthetic_api_456", b"synthetic_shell_789!",
                      b"synthetic_log_123", b"synthetic_log_pass_456!",
                      b"synthetic_file_log_789!", b"synthetic_file_hash_246"):
            self.assertNotIn(value, combined)
        self.assertIn(b"preserve_me", files["konfiguration/local.py"])
        self.assertIn(b'key = "public_method_name"', files["konfiguration/local.py"])
        self.assertIn(b"PASSWORD=$EXISTING_VALUE", files["konfiguration/local.sh"])

    def test_encoded_credential_payload_in_yaml_unknown_field_is_masked(self):
        encoded = base64.b64encode(b'{"pwd":"synthetic_yaml_payload_123"}').decode()
        self.fixture.write("configuration.yaml", "provider_blob: " + encoded + "\npublic: 0\n")
        _, _, files = self.fixture.build()
        output = yaml.safe_load(files["konfiguration/configuration.yaml"])
        self.assertEqual(output, {"provider_blob": "[MASKIERT]", "public": 0})

    def test_repeated_masking_does_not_learn_the_redaction_marker(self):
        redactor = Redactor()
        source = 'credentials_hash="synthetic_repeated_123" https://example.invalid/?apiKeyHash=synthetic_query_456'
        masked = redactor.source(source, ".txt")
        self.assertEqual(redactor.source(masked, ".txt"), masked)
        self.assertNotIn("[MASKIERT]", redactor.known)
        self.assertNotIn("[MASK]", redactor.known)
        self.assertIn("[MASKIERT]", masked)

    def test_basic_auth_in_log_and_sensitive_query_aliases_are_removed(self):
        encoded = base64.b64encode(b"synthetic_log_user:synthetic_log_password").decode()
        self.fixture.snapshot["files"]["diagnose/system_log.json"] = {"entries": [{
            "message": ["Authorization: Basic " + encoded +
                        " https://example.invalid/?credentialsHash=synthetic_query_hash&public=7"]}]}
        _, _, files = self.fixture.build()
        output = files["diagnose/system_log.json"].decode()
        for private in (encoded, "synthetic_log_user", "synthetic_log_password", "synthetic_query_hash"):
            self.assertNotIn(private, output)
        self.assertIn("public=7", output)

    def test_secret_matching_a_field_name_cannot_bypass_field_masking(self):
        redactor = Redactor()
        source = {"key": "password", "password": "ab"}
        redactor.learn(source)
        self.assertNotIn("ab", redactor.object(source).values())

    def test_long_public_source_token_is_preserved(self):
        # Large bundled frontend strings must not trigger repeated suffix scans.
        source = 'public_payload = "' + "A" * 100000 + '";\n'
        self.assertEqual(Redactor().source(source, ".js"), source)


if __name__ == "__main__":
    unittest.main()
