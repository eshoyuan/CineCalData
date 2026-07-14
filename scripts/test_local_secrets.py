import os
import unittest
from unittest.mock import patch

from local_secrets import read_secret


class LocalSecretsTests(unittest.TestCase):
    def test_environment_wins(self):
        with patch.dict(os.environ, {"MODEL_API_KEY": "from-environment"}):
            self.assertEqual(read_secret("MODEL_API_KEY"), "from-environment")

    def test_non_macos_without_environment_returns_empty(self):
        with patch.dict(os.environ, {}, clear=True), patch("platform.system", return_value="Linux"):
            self.assertEqual(read_secret("MODEL_API_KEY"), "")


if __name__ == "__main__":
    unittest.main()
