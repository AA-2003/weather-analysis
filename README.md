# Iran Weather Analysis

Collect weather for Iran's 31 provincial capitals, save hourly observations,
and plot temperature and humidity on an interactive map.

## Setup

Use Python 3.11 or 3.12.

```bash
git clone https://github.com/AA-2003/weather-analysis.git
cd weather-analysis
python -m venv .venv
```

Activate with `.\.venv\Scripts\Activate.ps1` on Windows or
`source .venv/bin/activate` on macOS / Linux, then install:

```bash
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your
[OpenWeather API key](https://openweathermap.org/appid).

## Run

```bash
python main.py
```

Each run makes 31 [Current Weather API](https://openweathermap.org/current) calls.
Temperatures are Celsius and observation hours are UTC. Existing observations
are updated by province and hour. Failed requests leave the CSV unchanged.

The CSV is saved to `data/weather.csv` and the map to `reports/weather.html`.
Open the HTML file in a browser; the base map needs internet access.
Use an existing CSV without API calls:

```bash
python main.py --input weather_data.csv
```

CSV columns: `province, city, longitude, latitude, temp, humidity, description, time`.
The reader also accepts the original `NAME_1`, `Longitude `, and `Latitude ` headers.

For province shading, supply a GeoJSON FeatureCollection whose
`properties.NAME_1` values match `provinces.py`:

```bash
python main.py --input weather_data.csv --geojson geojson/gadm41_IRN_1.json
```

The colours represent each province's capital, not an average across the province.
GADM files are not bundled; obtain them from [GADM](https://gadm.org/download_country.html)
under its [data terms](https://gadm.org/data.html).

## Notebook and tests

```bash
python -m pip install -r requirements-dev.txt
jupyter lab main.ipynb
python -m unittest discover -s tests -v
```

The notebook uses local CSV data when available. Tests use mocked API responses.
