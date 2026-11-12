#!/usr/bin/env python3
"""Exercise the local load driver's URL guard without making network requests."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().with_name("load-cache-db.sh")


class LoadDriverUrlTest(unittest.TestCase):
    def test_only_exact_local_origins_reach_curl(self):
        accepted = [
            "http://localhost",
            "http://localhost/app",
            "http://localhost:8080/app",
            "http://127.0.0.1",
            "http://127.0.0.1:8080/app",
        ]
        rejected = [
            "http://localhost:8080@example.com/app",
            "http://localhost:@example.com/app",
            "http://127.0.0.1:8080@example.com/app",
            "http://localhost.example.com/app",
            "http://127.0.0.1.example.com/app",
            "http://localhost:abc/app",
            "http://localhost:8080?@example.com",
            "http://localhost:8080#fragment",
            "http://localhost:8080\\@example.com/app",
            "https://example.com/app",
            "http://example.com/app",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = root / "curl-calls"
            curl = root / "curl"
            curl.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CURL_CALLS"\n')
            curl.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "CURL_CALLS": str(calls),
                "CONCURRENCY_LEVELS": "1",
                "REQUESTS_PER_WORKER": "1",
                "REQUEST_DELAY": "0",
                "USER_IDS": "1000",
            }
            for url in accepted + rejected:
                with self.subTest(url=url):
                    calls.unlink(missing_ok=True)
                    result = subprocess.run(
                        ["bash", str(SCRIPT)],
                        env={**environment, "BASE_URL": url},
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if url in accepted:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn(f"{url}/user/1000", calls.read_text())
                    else:
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertIn("BASE_URL must target", result.stderr)
                        self.assertFalse(calls.exists(), "Rejected URL reached curl")


if __name__ == "__main__":
    unittest.main()
