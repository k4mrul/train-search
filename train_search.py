import argparse
import json
import os
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

API_URL = "https://railspaapi.shohoz.com/v1.0/web/bookings/search-trips-v2"
PAGE_URL = "https://eticket.railway.gov.bd/booking/train/search"


def parse_cookie_string(raw: str) -> dict:
    cookies = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def load_cookie_file(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Cookie file must contain a JSON object like {\"name\": \"value\"}")
    return data


def api_params(fromcity: str, tocity: str, doj: str, train_class: str) -> dict:
    return {
        "from_city": fromcity,
        "to_city": tocity,
        "date_of_journey": doj,
        "seat_class": train_class,
    }


def build_headers(token: str, device_key: str, device_id: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Device-Key": device_key,
        "X-Device-Id": device_id,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://eticket.railway.gov.bd/",
        "Origin": "https://eticket.railway.gov.bd",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
    }


def is_json_response(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def parse_api_response(payload: dict) -> list[dict]:
    data = payload.get("data") or {}
    trains = []
    for train in data.get("trains", []):
        seat_types = []
        for seat in train.get("seat_types", []):
            counts = seat.get("seat_counts") or {}
            online = counts.get("online", 0) or 0
            offline = counts.get("offline", 0) or 0
            total = online + offline
            if total > 0:
                seat_types.append(
                    {
                        "name": seat.get("type"),
                        "fare": seat.get("fare"),
                        "online": online,
                        "offline": offline,
                        "total": total,
                    }
                )
        if seat_types:
            trains.append(
                {
                    "name": train.get("trip_number"),
                    "departure": train.get("departure_date_time_jd")
                    or train.get("departure_date_time"),
                    "arrival": train.get("arrival_date_time"),
                    "duration": train.get("travel_time"),
                    "from": train.get("origin_city_name"),
                    "to": train.get("destination_city_name"),
                    "classes": seat_types,
                }
            )
    return trains


def parse_page_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    trips = []
    for trip in soup.select("app-single-trip"):
        train_name_el = trip.select_one(".trip-left-info h2")
        start_date = trip.select_one(".journey-start .journey-date")
        start_loc = trip.select_one(".journey-start .journey-location")
        end_date = trip.select_one(".journey-end .journey-date")
        end_loc = trip.select_one(".journey-end .journey-location")
        duration = trip.select_one(".journey-duration")

        seat_classes = []
        for seat in trip.select(".single-seat-class"):
            seat_name_el = seat.select_one(".seat-class-name")
            if seat_name_el is None:
                continue
            fare_el = seat.select_one(".seat-class-fare")
            avail_el = seat.select_one(".all-seats")
            available = int(avail_el.get_text(strip=True)) if avail_el else 0
            if available > 0:
                seat_classes.append(
                    {
                        "name": seat_name_el.get_text(strip=True),
                        "fare": fare_el.get_text(strip=True) if fare_el else "",
                        "online": available,
                        "offline": 0,
                        "total": available,
                    }
                )

        if seat_classes:
            trips.append(
                {
                    "name": train_name_el.get_text(strip=True)
                    if train_name_el
                    else "Unknown train",
                    "departure": start_date.get_text(strip=True) if start_date else "",
                    "arrival": end_date.get_text(strip=True) if end_date else "",
                    "duration": duration.get_text(strip=True) if duration else "",
                    "from": start_loc.get_text(strip=True) if start_loc else "",
                    "to": end_loc.get_text(strip=True) if end_loc else "",
                    "classes": seat_classes,
                }
            )
    return trips


def filter_trips(trips: list[dict], train: str) -> list[dict]:
    if not train or train.lower() == "all":
        return trips
    needle = train.lower()
    return [t for t in trips if needle in t["name"].lower()]


def print_trips(trips: list[dict]) -> None:
    if not trips:
        print("No trains with available seats found.")
        return
    for trip in trips:
        print(f"\nTrain: {trip['name']}")
        print(f"Route: {trip['from']} -> {trip['to']}")
        print(
            f"Departure: {trip['departure']} | Arrival: {trip['arrival']} | "
            f"Duration: {trip['duration']}"
        )
        for seat in trip["classes"]:
            print(
                f"  {seat['name']}: {seat['fare']} - Online: {seat['online']}, "
                f"Counter: {seat['offline']}, Total: {seat['total']}"
            )
    print(f"\n{len(trips)} train(s) with available seats.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search Bangladesh Railway eticket availability via the Shohoz API."
    )
    parser.add_argument("--from", dest="fromcity", required=True, help="Departure city, e.g. Dhaka")
    parser.add_argument("--to", dest="tocity", required=True, help="Arrival city, e.g. Khulna")
    parser.add_argument("--doj", required=True, help="Date of journey, e.g. 07-Aug-2026")
    parser.add_argument("--class", dest="train_class", default="AC_S", help="Seat class, e.g. AC_S (default: AC_S)")
    parser.add_argument(
        "--train",
        default="PARJOTAK EXPRESS (816)",
        help="Filter by train name (substring, case-insensitive); pass 'all' for every train (default: PARJOTAK EXPRESS (816))",
    )
    parser.add_argument(
        "--device-key",
        default=os.environ.get(
            "SSDK",
            "7525b9e91c221ec9ac822ccebf0deba676b908ee2f3923d8b9ed8ad879ad595ecffd27592c8e8b679d4759a355c9416ffbf307c8933f5eb587c29f23365f59e664f3b805bddcd74b17ad74b74ead8b03",
        ),
        help="X-Device-Key from localStorage.getItem('ssdk'); defaults to $SSDK",
    )
    parser.add_argument(
        "--device-id",
        default=os.environ.get(
            "UUDID",
            "adc80545319c3d946cf7ee25cfce5cc5",
        ),
        help="X-Device-Id from localStorage.getItem('uudid'); defaults to $UUDID",
    )
    parser.add_argument(
        "--cookies",
        help="Raw cookie string for HTML fallback, e.g. 'JSESSIONID=abc; _csrf=xyz'",
    )
    parser.add_argument(
        "--cookies-file",
        type=Path,
        help="Path to a JSON cookie file for the HTML fallback",
    )
    parser.add_argument(
        "--save-html",
        type=Path,
        help="Optional path to save the raw response for debugging",
    )
    args = parser.parse_args()

    token = os.environ.get("TOKEN")
    if not token:
        print("TOKEN environment variable is not set.", file=sys.stderr)
        print("Export it first:", file=sys.stderr)
        print("  export TOKEN='<from localStorage.getItem(\"token\")>'", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers.update(build_headers(token, args.device_key, args.device_id))
    params = api_params(args.fromcity, args.tocity, args.doj, args.train_class)

    try:
        resp = session.get(API_URL, params=params, timeout=30)
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    if args.save_html:
        args.save_html.write_bytes(resp.content)

    if resp.status_code == 401:
        print("Authentication failed: invalid or expired token.", file=sys.stderr)
        print("Get a fresh one from the browser console:", file=sys.stderr)
        print("  localStorage.getItem('token')", file=sys.stderr)
        return 1

    if is_json_response(resp.text):
        try:
            payload = resp.json()
        except ValueError:
            print("Response was not valid JSON.", file=sys.stderr)
            return 1
        trips = parse_api_response(payload)
        trips = filter_trips(trips, args.train)
        print_trips(trips)
        return 0

    cookies = {}
    if args.cookies:
        cookies.update(parse_cookie_string(args.cookies))
    if args.cookies_file:
        cookies.update(load_cookie_file(args.cookies_file))
    session.cookies.update(cookies)

    page_resp = session.get(
        PAGE_URL,
        params={
            "fromcity": args.fromcity,
            "tocity": args.tocity,
            "doj": args.doj,
            "class": args.train_class,
        },
        timeout=30,
    )
    if page_resp.status_code != 200:
        print(f"HTML fallback failed with status {page_resp.status_code}.", file=sys.stderr)
        return 1
    trips = parse_page_html(page_resp.text)
    trips = filter_trips(trips, args.train)
    print_trips(trips)
    return 0


if __name__ == "__main__":
    sys.exit(main())
