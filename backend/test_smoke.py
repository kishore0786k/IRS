import unittest

from app import app


class ApiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.payload = {"mode": "fast", "seed": 2026}

    def post_json(self, endpoint, payload=None):
        response = self.client.post(endpoint, json=payload or self.payload)
        self.assertEqual(response.status_code, 200, msg=response.get_data(as_text=True)[:300])
        return response.get_json()

    def test_core_metrics_include_metadata(self):
        data = self.post_json("/api/metrics")
        self.assertIn("avg_snr_db", data)
        self.assertIn("avg_noma", data)
        self.assertIn("metadata", data)
        self.assertEqual(data["metadata"]["mode"], "fast")
        self.assertNotIn("snr_samples_db", data)

    def test_overview_bundle_matches_frontend_contract(self):
        data = self.post_json("/api/overview")
        self.assertIn("metrics", data)
        self.assertIn("distance", data)
        self.assertIn("N", data)
        self.assertIn("bits", data)
        self.assertIn("noma", data)
        self.assertIn("metadata", data)

    def test_sweep_payloads_match_frontend_contract(self):
        sweep_n = self.post_json("/api/sweep/N")
        self.assertIn("opt", sweep_n)
        self.assertIn("none_line", sweep_n)
        self.assertIn("mean", sweep_n["opt"])

        csi = self.post_json("/api/sweep/csi")
        self.assertIn("gain_vs_greedy_pct", csi)
        self.assertEqual(len(csi["csi_error"]), len(csi["gain_vs_greedy_pct"]))

    def test_comparison_includes_fairness(self):
        rows = self.post_json("/api/compare")
        self.assertTrue(rows)
        self.assertIn("fairness", rows[0])
        self.assertIn("gain_vs_greedy_pct", rows[0])
        greedy = next(row for row in rows if row["scheme"] == "greedy")
        self.assertAlmostEqual(greedy["gain_vs_greedy_pct"], 0.0, places=6)
        self.assertIn("rate_gain_vs_ao_lit_pct", rows[0])
        self.assertIn("secrecy_ci95", rows[0])
        self.assertTrue(any(row["scheme"] == "ao_lit" for row in rows))

    def test_convergence_endpoint_exists(self):
        data = self.post_json("/api/convergence")
        self.assertIn("convergence", data)
        self.assertGreater(len(data["convergence"]), 0)

    def test_export_writes_manifest(self):
        png_data_url = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAoMBgAqXWiwAAAAASUVORK5CYII="
        )
        data = self.post_json("/api/export", {
            "charts": [{"filename": "smoke.png", "data": png_data_url}],
            "params": self.payload,
            "mode": "fast",
        })
        self.assertEqual(data["count"], 1)
        self.assertIn("manifest", data)


if __name__ == "__main__":
    unittest.main()
