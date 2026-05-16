import unittest

from intruder.script_loader import AVAILABLE_SCRIPTS, build_agent


class ScriptLoaderTests(unittest.TestCase):
    def test_available_scripts_excludes_internal_debug_bundle(self) -> None:
        self.assertNotIn("_debug_agent", AVAILABLE_SCRIPTS)

    def test_build_agent_injects_libc_default_config(self) -> None:
        source = build_agent(["libc"], debug=False)
        self.assertIn("module.type = 'libc';", source)
        self.assertIn('"send": true', source)
        self.assertIn('"recv": true', source)
        self.assertIn('"shutdown": true', source)
        self.assertIn('"close": true', source)

    def test_build_agent_injects_gnutls_default_config(self) -> None:
        source = build_agent(["gnutls"], debug=False)
        self.assertIn("module.type = 'gnutls';", source)
        self.assertIn('"gnutls_record_send": true', source)
        self.assertIn('"gnutls_record_recv": true', source)
        self.assertIn('"gnutls_bye": true', source)

    def test_build_agent_rejects_unknown_script(self) -> None:
        with self.assertRaises(ValueError):
            build_agent(["not-a-script"], debug=False)


if __name__ == "__main__":
    unittest.main()
