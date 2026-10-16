import json
import os
from pathlib import Path
import tempfile

import pandas as pd
import plotly.express as px
import requests
from dotenv import load_dotenv

from provinces import PROVINCE_CAPITALS

ROOT = Path(__file__).resolve().parent
COLUMNS = [
    "province", "city", "longitude", "latitude",
    "temp", "humidity", "description", "time",
]
API_URL = "https://api.openweathermap.org/data/2.5/weather"


class WeatherFetchError(RuntimeError):
    pass


def fetch_weather(api_key=None, session=None):
    load_dotenv(ROOT / ".env")
    api_key = (api_key or os.environ.get("OPENWEATHER_API_KEY", "")).strip()
    if not api_key:
        raise WeatherFetchError("Set OPENWEATHER_API_KEY in .env or the environment.")

    owns_session = session is None
    session = session if session is not None else requests.Session()
    rows = []
    try:
        for province, city in PROVINCE_CAPITALS.items():
            try:
                response = session.get(
                    API_URL,
                    params={"q": f"{city},IR", "appid": api_key, "units": "metric"},
                    timeout=20,
                )
            except requests.RequestException:
                raise WeatherFetchError(f"Weather request failed for {city}.") from None
            if response.status_code != 200:
                raise WeatherFetchError(
                    f"Weather request failed for {city} (HTTP {response.status_code})."
                )
            try:
                data = response.json()
                if data["sys"]["country"] != "IR":
                    raise ValueError("Unexpected country")
                rows.append({
                    "province": province,
                    "city": city,
                    "longitude": data["coord"]["lon"],
                    "latitude": data["coord"]["lat"],
                    "temp": data["main"]["temp"],
                    "humidity": data["main"]["humidity"],
                    "description": data["weather"][0]["description"],
                    "time": pd.to_datetime(data["dt"], unit="s", utc=True).floor("h"),
                })
            except (KeyError, IndexError, ValueError, TypeError):
                raise WeatherFetchError(f"Invalid weather response for {city}.") from None
    finally:
        if owns_session:
            session.close()
    return normalise_weather(pd.DataFrame(rows))


def normalise_weather(frame):
    frame = frame.copy()
    frame.columns = [str(name).strip() for name in frame.columns]
    frame = frame.rename(columns={
        "NAME_1": "province", "Longitude": "longitude", "Latitude": "latitude",
    })
    if "province" not in frame:
        raise ValueError("Weather data is missing the province column.")
    frame["province"] = frame["province"].replace({"Isfahan": "Esfahan"})
    if "city" not in frame:
        frame["city"] = frame["province"].map(PROVINCE_CAPITALS)
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError("Weather data is missing columns: " + ", ".join(sorted(missing)))
    if frame.empty:
        raise ValueError("Weather data is empty.")
    if not frame["province"].isin(PROVINCE_CAPITALS).all():
        raise ValueError("Weather data contains an unknown province.")
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="raise").dt.floor("h")
    for name in ["longitude", "latitude", "temp", "humidity"]:
        frame[name] = pd.to_numeric(frame[name], errors="raise")
    if frame[COLUMNS].isna().any().any():
        raise ValueError("Weather data contains missing values.")
    if not frame["longitude"].between(-180, 180).all():
        raise ValueError("Longitude must be between -180 and 180.")
    if not frame["latitude"].between(-90, 90).all():
        raise ValueError("Latitude must be between -90 and 90.")
    if not frame["humidity"].between(0, 100).all():
        raise ValueError("Humidity must be between 0 and 100.")
    return frame[COLUMNS].reset_index(drop=True)


def read_weather(path):
    return normalise_weather(pd.read_csv(path))


def append_weather(frame, path):
    path = Path(path)
    frame = normalise_weather(frame)
    if path.exists():
        frame = pd.concat([read_weather(path), frame], ignore_index=True)
    frame = (
        frame.drop_duplicates(["province", "time"], keep="last")
        .sort_values(["time", "province"])
        .reset_index(drop=True)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            frame.to_csv(handle, index=False)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return frame


def create_map(frame, geojson_path=None):
    frame = normalise_weather(frame)
    latest = frame.sort_values("time").drop_duplicates("province", keep="last")
    options = {
        "color": "temp",
        "hover_name": "city",
        "hover_data": {"province": True, "humidity": True, "description": True, "time": True},
        "color_continuous_scale": "RdYlBu_r",
        "labels": {"temp": "Temperature (C)", "humidity": "Humidity (%)"},
        "title": "Weather in Iran's provincial capitals",
    }
    if geojson_path is not None:
        with Path(geojson_path).open(encoding="utf-8") as handle:
            boundaries = json.load(handle)
        if boundaries.get("type") != "FeatureCollection":
            raise ValueError("Boundary data must be a GeoJSON FeatureCollection.")
        names = {
            feature.get("properties", {}).get("NAME_1")
            for feature in boundaries.get("features", [])
        }
        missing = set(latest["province"]) - names
        if missing:
            raise ValueError("Missing map boundaries: " + ", ".join(sorted(missing)))
        fig = px.choropleth(
            latest, geojson=boundaries, featureidkey="properties.NAME_1",
            locations="province", **options,
        )
        fig.update_geos(fitbounds="locations", visible=False)
    else:
        fig = px.scatter_geo(
            latest, lat="latitude", lon="longitude", **options,
        )
        fig.update_traces(marker={"size": 12})
        fig.update_geos(fitbounds="locations", showcountries=True)
    fig.update_layout(margin={"r": 0, "l": 0, "b": 0})
    return fig
