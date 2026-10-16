import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

import main
from provinces import PROVINCE_CAPITALS
from weather import (
    COLUMNS, WeatherFetchError, append_weather, create_map,
    fetch_weather, normalise_weather, read_weather,
)

FIXTURE = Path(__file__).parent / "fixtures/synthetic_weather.csv"


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.frame = read_weather(FIXTURE)

    def test_legacy_csv_headers_and_timezone_are_normalised(self):
        legacy = self.frame.drop(columns="city").rename(columns={
            "province": "NAME_1", "longitude": "Longitude ", "latitude": "Latitude ",
        })
        legacy["geometry"] = "POINT (0 0)"
        legacy["time"] = "2025-01-01 10:37:00"
        result = normalise_weather(legacy)
        self.assertEqual(list(result.columns), COLUMNS)
        self.assertEqual(result.iloc[0]["city"], "Tehran")
        self.assertEqual(result.iloc[0]["time"], pd.Timestamp("2025-01-01T10:00:00Z"))

    def test_unknown_provinces_and_missing_observations_are_rejected(self):
        cases = [
            self.frame.assign(province="Unknown"),
            self.frame.assign(humidity=101),
            self.frame.assign(latitude=100),
            self.frame.assign(temp=None),
            self.frame.drop(columns="time"),
            self.frame.iloc[:0],
        ]
        for frame in cases:
            with self.subTest(columns=list(frame.columns), rows=len(frame)):
                with self.assertRaises(ValueError):
                    normalise_weather(frame)

    def test_append_updates_existing_hour_and_preserves_other_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested/weather.csv"
            append_weather(self.frame, path)
            update = self.frame.iloc[[0]].copy()
            update["temp"] = 25
            append_weather(update, path)
            later = update.copy()
            later["time"] = "2025-01-01T11:00:00Z"
            result = append_weather(later, path)
            self.assertEqual(len(result), 3)
            tehran = result[result["province"] == "Tehran"]
            self.assertEqual(tehran["temp"].tolist(), [25, 25])
            self.assertEqual(len(result[result["province"] == "Esfahan"]), 1)
            self.assertEqual(len(read_weather(path)), 3)

    def test_failed_write_keeps_existing_csv_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weather.csv"
            append_weather(self.frame, path)
            original = path.read_bytes()
            with patch("weather.pd.DataFrame.to_csv", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    append_weather(self.frame, path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_requests_cover_31_unique_capitals_in_iran(self):
        session = Mock()
        response = session.get.return_value
        response.status_code = 200
        response.json.return_value = {
            "sys": {"country": "IR"},
            "coord": {"lon": 51.4, "lat": 35.7},
            "main": {"temp": 20, "humidity": 40},
            "weather": [{"description": "clear sky"}],
            "dt": 1735727820,
        }
        result = fetch_weather("test-api-key", session=session)
        self.assertEqual(len(PROVINCE_CAPITALS), 31)
        self.assertEqual(result["province"].nunique(), 31)
        queries = [call.kwargs["params"]["q"] for call in session.get.call_args_list]
        self.assertEqual(len(set(queries)), 31)
        self.assertTrue(all(query.endswith(",IR") for query in queries))
        self.assertTrue(all(call.args[0].startswith("https://") for call in session.get.call_args_list))
        self.assertTrue(all(call.kwargs["timeout"] > 0 for call in session.get.call_args_list))

    def test_http_and_network_errors_never_expose_the_key(self):
        for status in [401, 429, 500]:
            with self.subTest(status=status):
                session = Mock()
                session.get.return_value.status_code = status
                with self.assertRaises(WeatherFetchError) as error:
                    fetch_weather("secret-test-key", session=session)
                self.assertIn(f"HTTP {status}", str(error.exception))
                self.assertNotIn("secret-test-key", str(error.exception))
        session = Mock()
        session.get.side_effect = requests.ConnectionError(
            "https://example.invalid/?appid=secret-test-key"
        )
        with self.assertRaises(WeatherFetchError) as error:
            fetch_weather("secret-test-key", session=session)
        self.assertNotIn("secret-test-key", str(error.exception))

    def test_invalid_api_payload_is_rejected(self):
        session = Mock()
        session.get.return_value.status_code = 200
        for payload in [{}, {"sys": {"country": "US"}}]:
            session.get.return_value.json.return_value = payload
            with self.subTest(payload=payload):
                with self.assertRaises(WeatherFetchError):
                    fetch_weather("test-api-key", session=session)

    def test_missing_key_does_not_make_requests(self):
        with patch("weather.load_dotenv"), patch.dict(os.environ, {}, clear=True):
            session = Mock()
            with self.assertRaisesRegex(WeatherFetchError, "OPENWEATHER_API_KEY"):
                fetch_weather(session=session)
            session.get.assert_not_called()

    def test_point_map_uses_latest_observation_for_each_province(self):
        later = self.frame.iloc[[0]].copy()
        later["time"] = "2025-01-01T11:00:00Z"
        later["temp"] = 30
        fig = create_map(pd.concat([self.frame, later], ignore_index=True))
        self.assertEqual(fig.data[0].type, "scattergeo")
        self.assertEqual(len(fig.data[0].lat), 2)
        self.assertIn(30, fig.data[0].marker.color)
        self.assertNotIn(20, fig.data[0].marker.color)

    def test_province_map_matches_names_and_rejects_missing_boundaries(self):
        boundaries = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature", "properties": {"NAME_1": name},
                    "geometry": {"type": "Polygon", "coordinates": [
                        [[0, 0], [1, 0], [1, 1], [0, 0]]
                    ]},
                }
                for name in self.frame["province"]
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.geojson"
            path.write_text(json.dumps(boundaries), encoding="utf-8")
            fig = create_map(self.frame, path)
            self.assertEqual(fig.data[0].type, "choropleth")
            self.assertEqual(set(fig.data[0].locations), set(self.frame["province"]))
            boundaries["features"].pop()
            path.write_text(json.dumps(boundaries), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Missing map boundaries"):
                create_map(self.frame, path)

    def test_cli_reads_csv_without_calling_api_or_modifying_input(self):
        with tempfile.TemporaryDirectory() as directory:
            html = Path(directory) / "map.html"
            original = FIXTURE.read_bytes()
            with patch("main.fetch_weather") as fetch:
                main.main(["--input", str(FIXTURE), "--html", str(html)])
                fetch.assert_not_called()
            self.assertIn("plotly", html.read_text(encoding="utf-8").lower())
            self.assertEqual(FIXTURE.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
