import argparse
import json
import os
import sys

import requests

API_BASE = "https://railspaapi.shohoz.com/v1.0/web/bookings"
SEARCH_URL = f"{API_BASE}/search-trips-v2"
LAYOUT_URL = f"{API_BASE}/seat-layout"
RESERVE_URL = f"{API_BASE}/reserve-seat"


def build_headers(token: str, device_key: str, device_id: str, action_token: str = "") -> dict:
    headers = {
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
    if action_token:
        headers["X-Action-Token"] = action_token
    return headers


def title_case(s: str) -> str:
    return " ".join(word.capitalize() for word in s.split())


def require_token() -> str:
    token = os.environ.get("TOKEN")
    if not token:
        print("TOKEN environment variable is not set.", file=sys.stderr)
        print("Export it first:", file=sys.stderr)
        print("  export TOKEN='<from localStorage.getItem(\"token\")>'", file=sys.stderr)
        sys.exit(1)
    return token


def search_trips(session, fromcity, tocity, doj, train_class, train_filter) -> list[dict]:
    params = {
        "from_city": fromcity,
        "to_city": tocity,
        "date_of_journey": doj,
        "seat_class": train_class,
    }
    resp = session.get(SEARCH_URL, params=params, timeout=30)
    if resp.status_code == 401:
        print("Search failed: invalid or expired token. Refresh TOKEN.", file=sys.stderr)
        sys.exit(1)
    if not resp.text.lstrip().startswith(("{")):
        print(f"Search failed with status {resp.status_code}.", file=sys.stderr)
        sys.exit(1)
    payload = resp.json()
    data = payload.get("data") or {}
    trips = []
    for train in data.get("trains", []):
        seat_types = []
        for seat in train.get("seat_types", []):
            counts = seat.get("seat_counts") or {}
            total = (counts.get("online") or 0) + (counts.get("offline") or 0)
            if total <= 0:
                continue
            seat_types.append(
                {
                    "name": seat.get("type"),
                    "trip_id": seat.get("trip_id"),
                    "trip_route_id": seat.get("trip_route_id"),
                    "fare": seat.get("fare"),
                    "online": counts.get("online"),
                    "offline": counts.get("offline"),
                    "total": total,
                }
            )
        if not seat_types:
            continue
        trips.append(
            {
                "name": train.get("trip_number"),
                "departure": train.get("departure_date_time_jd")
                or train.get("departure_date_time"),
                "arrival": train.get("arrival_date_time"),
                "duration": train.get("travel_time"),
                "origin": train.get("origin_city_name"),
                "destination": train.get("destination_city_name"),
                "seat_types": seat_types,
            }
        )
    if train_filter and train_filter.lower() != "all":
        needle = train_filter.lower()
        trips = [t for t in trips if needle in t["name"].lower()]
    return trips


def fetch_seat_layout(session, trip_id, trip_route_id, cft_response) -> requests.Response:
    params = {
        "trip_id": trip_id,
        "trip_route_id": trip_route_id,
    }
    if cft_response:
        params["cft_response"] = cft_response
    return session.get(LAYOUT_URL, params=params, timeout=30)


def pick_available_seat(layout_payload, preferred_seat: str | None) -> dict | None:
    floors = (layout_payload.get("data") or {}).get("seatLayout", [])
    if preferred_seat:
        for floor in floors:
            for row in floor.get("layout", []):
                for seat in row:
                    if (
                        seat.get("seat_number") == preferred_seat
                        and seat.get("seat_availability")
                    ):
                        return seat
        return None
    for floor in floors:
        for row in floor.get("layout", []):
            for seat in row:
                if seat.get("seat_availability") and seat.get("seat_number"):
                    return seat
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Full Bangladesh Railway eticket flow: search -> seat layout -> reserve."
    )
    parser.add_argument("--from", dest="fromcity", required=True, help="Departure city, e.g. Dhaka")
    parser.add_argument("--to", dest="tocity", required=True, help="Arrival city, e.g. Khulna")
    parser.add_argument("--doj", required=True, help="Date of journey, e.g. 07-Aug-2026")
    parser.add_argument("--class", dest="train_class", default="AC_S", help="Seat class (default: AC_S)")
    parser.add_argument(
        "--train",
        default="PARJOTAK EXPRESS (816)",
        help="Filter by train name (substring); 'all' for every train (default: PARJOTAK EXPRESS (816))",
    )
    parser.add_argument(
        "--seat-class",
        help="Reserve this seat class (defaults to --class)",
    )
    parser.add_argument(
        "--seat",
        help="Reserve this exact seat number (e.g. JHA-1); otherwise the first available seat is used",
    )
    parser.add_argument(
        "--device-key",
        default=os.environ.get(
            "SSDK",
            "7525b9e91c221ec9ac822ccebf0deba676b908ee2f3923d8b9ed8ad879ad595ecffd27592c8e8b679d4759a355c9416ffbf307c8933f5eb587c29f23365f59e664f3b805bddcd74b17ad74b74ead8b03",
        ),
        help="X-Device-Key / localStorage 'ssdk'; defaults to $SSDK",
    )
    parser.add_argument(
        "--device-id",
        default=os.environ.get(
            "UUDID",
            "adc80545319c3d946cf7ee25cfce5cc5",
        ),
        help="X-Device-Id / localStorage 'uudid'; defaults to $UUDID",
    )
    parser.add_argument(
        "--cft-response",
        default=os.environ.get("CFT_RESPONSE", ""),
        help="Cloudflare Turnstile token for seat-layout (from browser); omit if not enforced",
    )
    parser.add_argument(
        "--action-token",
        default=os.environ.get("ACTION_TOKEN", ""),
        help="Turnstile sequential action token for reserve-seat (from browser); omit if not enforced",
    )
    parser.add_argument(
        "--action-token-header",
        default=os.environ.get("X_ACTION_TOKEN", ""),
        help="X-Action-Token header override (normally auto-captured from the seat-layout response)",
    )
    args = parser.parse_args()

    token = require_token()
    session = requests.Session()
    session.headers.update(build_headers(token, args.device_key, args.device_id))

    print("[1/3] Searching trips...")
    trips = search_trips(
        session, args.fromcity, args.tocity, args.doj, args.train_class, args.train
    )
    if not trips:
        print("No trains with available seats found.")
        return 1
    trip = trips[0]

    seat_class = args.seat_class or args.train_class
    seat_type = next(
        (s for s in trip["seat_types"] if s["name"] == seat_class),
        trip["seat_types"][0],
    )
    if seat_type["name"] != seat_class:
        print(
            f"'{seat_class}' has no seats on {trip['name']}; using {seat_type['name']} instead.",
            file=sys.stderr,
        )
    print(
        f"  {trip['name']} | {trip['departure']} -> {trip['arrival']} | "
        f"{trip['duration']} | {seat_type['name']}: {seat_type['total']} available"
    )

    print("[2/3] Fetching seat layout...")
    layout_resp = fetch_seat_layout(
        session, seat_type["trip_id"], seat_type["trip_route_id"], args.cft_response
    )
    if layout_resp.status_code == 401:
        print("Seat layout failed: invalid/expired token.", file=sys.stderr)
        return 1
    action_token_header = args.action_token_header or layout_resp.headers.get(
        "X-Action-Token", ""
    )
    if not action_token_header:
        print(
            "Note: no X-Action-Token header received; continuing without it.",
            file=sys.stderr,
        )
    try:
        layout_payload = layout_resp.json()
    except ValueError:
        print(
            f"Seat layout returned status {layout_resp.status_code} with non-JSON body:",
            file=sys.stderr,
        )
        print(layout_resp.text[:2000], file=sys.stderr)
        return 1
    layout_data = layout_payload.get("data")
    if not layout_data or not layout_data.get("seatLayout"):
        print(
            "Seat layout returned no seat data. Raw response:", file=sys.stderr
        )
        print(json.dumps(layout_payload, indent=2)[:2000], file=sys.stderr)
        if layout_data and layout_data.get("error"):
            print(
                f"Server error: {layout_data.get('message') or layout_data.get('error')}",
                file=sys.stderr,
            )
        if not args.cft_response:
            print(
                "The seat-layout endpoint likely requires a Cloudflare Turnstile token.\n"
                "Export CFT_RESPONSE (grab it from browser DevTools -> Network while\n"
                "clicking BOOK NOW, from the seat-layout request URL) and retry.",
                file=sys.stderr,
            )
        return 1
    seat = pick_available_seat(layout_payload, args.seat)
    if not seat:
        print("No available seat in the layout.", file=sys.stderr)
        if args.seat:
            print(f"Seat '{args.seat}' is not available.", file=sys.stderr)
        return 1
    print(f"  Selected seat: {seat['seat_number']} (ticket_id={seat['ticket_id']})")

    print("[3/3] Reserving seat...")
    reserve_headers = build_headers(
        token, args.device_key, args.device_id, action_token_header
    )
    reserve_headers["Content-Type"] = "application/json"
    body = {
        "ticket_id": seat["ticket_id"],
        "route_id": seat_type["trip_route_id"],
        "extras": {
            "seat_number": seat["seat_number"],
            "trip_number": trip["name"],
            "origin_name": title_case(trip["origin"]),
            "destination_name": title_case(trip["destination"]),
        },
        "action_token": args.action_token,
    }
    reserve_resp = session.patch(RESERVE_URL, json=body, headers=reserve_headers, timeout=30)

    print(f"  Status: {reserve_resp.status_code}")
    try:
        result = reserve_resp.json()
        print(json.dumps(result, indent=2))
    except ValueError:
        print(reserve_resp.text)
    if reserve_resp.status_code == 401:
        print("Reserve failed: invalid/expired token.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
