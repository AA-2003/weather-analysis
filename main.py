import argparse
from pathlib import Path

from weather import WeatherFetchError, append_weather, create_map, fetch_weather, read_weather

ROOT = Path(__file__).resolve().parent


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Collect and map weather for Iran's capitals.")
    parser.add_argument("--input", type=Path, help="Read an existing CSV instead of calling the API")
    parser.add_argument("--output", type=Path, default=ROOT / "data/weather.csv")
    parser.add_argument("--html", type=Path, default=ROOT / "reports/weather.html")
    parser.add_argument("--geojson", type=Path, help="Province boundaries with properties.NAME_1")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.input:
        frame = read_weather(args.input)
    else:
        frame = fetch_weather()
        frame = append_weather(frame, args.output)
        print(f"Saved weather data to {args.output}")

    figure = create_map(frame, args.geojson)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(args.html, include_plotlyjs=True)
    print(f"Saved map to {args.html}")


if __name__ == "__main__":
    try:
        main()
    except (WeatherFetchError, ValueError, OSError) as error:
        raise SystemExit(str(error)) from None
