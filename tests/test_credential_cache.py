"""Regression coverage without requiring a running Home Assistant installation."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "credential_cache",
    Path(__file__).resolve().parents[1]
    / "custom_components/kumo/credential_cache.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
preserve_cached_credentials = module.preserve_cached_credentials


def response(units):
    return [{}, {}, {"children": [{"zoneTable": units}]}]


class CredentialCacheTest(unittest.TestCase):
    def test_omitted_credentials_survive_cloud_refresh(self):
        cached = response({"one": {"password": "cached", "cryptoSerial": "serial"}})
        original = copy.deepcopy(cached)
        fresh = response({"one": {"password": "", "cryptoSerial": "", "label": "New name"}})
        self.assertTrue(preserve_cached_credentials(fresh, cached))
        self.assertEqual(fresh[2]["children"][0]["zoneTable"]["one"], {
            "password": "cached", "cryptoSerial": "serial", "label": "New name",
        })
        self.assertEqual(cached, original)

    def test_fresh_credentials_take_precedence(self):
        fresh = response({"one": {"password": "new", "cryptoSerial": "new serial"}})
        expected = copy.deepcopy(fresh)
        self.assertTrue(preserve_cached_credentials(fresh, response({
            "one": {"password": "old", "cryptoSerial": "old serial"},
        })))
        self.assertEqual(fresh, expected)

    def test_credentials_are_never_shared_between_devices(self):
        fresh = response({"other": {}})
        self.assertFalse(preserve_cached_credentials(fresh, response({
            "one": {"password": "cached", "cryptoSerial": "serial"},
        })))
        self.assertEqual(fresh, response({"other": {}}))

    def test_nested_devices_and_empty_cache(self):
        fresh = [{}, {}, {"children": [{"children": [{"zoneTable": {
            "one": {"password": "fresh", "cryptoSerial": "serial"},
        }}]}]}]
        self.assertTrue(preserve_cached_credentials(fresh, None))
        self.assertFalse(preserve_cached_credentials(response({}), None))


if __name__ == "__main__":
    unittest.main()
