import argparse
import base64
import json
import os
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

SEARCH_URL = "https://eticket.railway.gov.bd/booking/train/search"

DEVICE_KEY = os.environ.get(
    "SSDK",
    "7525b9e91c221ec9ac822ccebf0deba676b908ee2f3923d8b9ed8ad879ad595ecffd27592c8e8b679d4759a355c9416ffbf307c8933f5eb587c29f23365f59e664f3b805bddcd74b17ad74b74ead8b03",
)
DEVICE_ID = os.environ.get("UUDID", "adc80545319c3d946cf7ee25cfce5cc5")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

TURNSTILE_STUB = """(() => {
  const noop = () => {};
  window.turnstile = {
    render: (container, params) => {
      if (params && typeof params.callback === "function") {
        setTimeout(() => params.callback("dummy-token"), 10);
      }
      return 0;
    },
    execute: (action, params) => {
      if (params && typeof params.callback === "function") {
        setTimeout(() => params.callback("dummy-token"), 10);
      }
      return Promise.resolve("dummy-token");
    },
    reset: noop,
    remove: noop,
    getResponse: () => "dummy-token",
    isReady: () => true,
  };
  const onload = new URLSearchParams(location.search).get("onload");
  if (onload && typeof window[onload] === "function") window[onload]();
})();"""


def handle_turnstile_route(route) -> None:
    if "api.js" in route.request.url:
        route.fulfill(
            status=200,
            content_type="application/javascript",
            body=TURNSTILE_STUB,
        )
    else:
        route.abort()


def handle_handshake_route(route) -> None:
    try:
        resp = route.fetch()
        body = resp.json()
        data = body.get("data")
        if isinstance(data, dict) and isinstance(data.get("turnstile"), dict):
            data["turnstile"] = {
                "sequential_action_token_enabled": False,
                "visible_enabled": False,
                "invisible_enabled": False,
            }
            route.fulfill(status=resp.status, headers=resp.headers, json=body)
            return
    except Exception:
        pass
    route.continue_()


def handle_booking_route(route) -> None:
    url = route.request.url
    if "cft_response" in url or "action_token=dummy-token" in url:
        parts = urlsplit(url)
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query)
            if k != "cft_response" and not (k == "action_token" and v == "dummy-token")
        ]
        route.continue_(
            url=urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
            )
        )
    else:
        route.continue_()


def build_search_url(fromcity: str, tocity: str, doj: str, train_class: str) -> str:
    return (
        f"{SEARCH_URL}?fromcity={fromcity}&tocity={tocity}"
        f"&doj={doj}&class={train_class}"
    )


def build_user_object(token: str) -> dict:
    user = {
        "display_name": "",
        "username": "",
        "mobile_number": "",
        "phone_number": "",
        "email": "",
        "nidn": "",
        "nid_validated": True,
        "is_nid_verification_required": False,
    }
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        user["display_name"] = claims.get("display_name", "")
        user["username"] = claims.get("username", "")
        user["mobile_number"] = claims.get("phone_number", "")
        user["phone_number"] = claims.get("phone_number", "")
        user["email"] = claims.get("email", "")
        user["nidn"] = claims.get("nidn", "")
    except Exception:
        pass
    return user


def auth_init_script(token: str, device_key: str, device_id: str) -> str:
    return f"""
    try {{
        localStorage.setItem('token', {json.dumps(token)});
        localStorage.setItem('user', {json.dumps(json.dumps(build_user_object(token)))});
        localStorage.setItem('ssdk', {json.dumps(device_key)});
        localStorage.setItem('uudid', {json.dumps(device_id)});
    }} catch (e) {{}}
    """


def set_local_storage(page, token: str, device_key: str, device_id: str) -> None:
    page.evaluate(
        "([token, user, ssdk, uudid]) => {"
        "try { localStorage.setItem('token', token);"
        "localStorage.setItem('user', JSON.stringify(user));"
        "localStorage.setItem('ssdk', ssdk);"
        "localStorage.setItem('uudid', uudid); } catch (e) {}"
        "}",
        [token, build_user_object(token), device_key, device_id],
    )


def is_logged_in(page) -> bool:
    return page.evaluate(
        "() => {"
        "const token = localStorage.getItem('token');"
        "if (!token) return false;"
        "try {"
        "  const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));"
        "  return payload.exp * 1000 > Date.now();"
        "} catch (e) { return Boolean(token); }"
        "}"
    )


def parse_trips_from_page(page) -> list[dict]:
    return page.evaluate(
        """() => {
            const trips = [];
            for (const trip of document.querySelectorAll('app-single-trip')) {
                const nameEl = trip.querySelector('.trip-left-info h2');
                const startDate = trip.querySelector('.journey-start .journey-date');
                const startLoc = trip.querySelector('.journey-start .journey-location');
                const endDate = trip.querySelector('.journey-end .journey-date');
                const endLoc = trip.querySelector('.journey-end .journey-location');
                const duration = trip.querySelector('.journey-duration');
                const classes = [];
                for (const seat of trip.querySelectorAll('.single-seat-class')) {
                    const nameEl2 = seat.querySelector('.seat-class-name');
                    if (!nameEl2) continue;
                    const fareEl = seat.querySelector('.seat-class-fare');
                    const availEl = seat.querySelector('.all-seats');
                    const available = availEl ? parseInt(availEl.textContent.trim(), 10) || 0 : 0;
                    if (available > 0) {
                        classes.push({
                            name: nameEl2.textContent.trim(),
                            fare: fareEl ? fareEl.textContent.trim() : '',
                            online: available,
                            offline: 0,
                            total: available,
                        });
                    }
                }
                if (classes.length) {
                    trips.push({
                        name: nameEl ? nameEl.textContent.trim() : 'Unknown train',
                        departure: startDate ? startDate.textContent.trim() : '',
                        arrival: endDate ? endDate.textContent.trim() : '',
                        duration: duration ? duration.textContent.trim() : '',
                        from: startLoc ? startLoc.textContent.trim() : '',
                        to: endLoc ? endLoc.textContent.trim() : '',
                        classes: classes,
                    });
                }
            }
            return trips;
        }"""
    )


def print_trips(trips: list[dict]) -> None:
    if not trips:
        print("No trains with available seats found on the page.")
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


def click_book_now(
    page, train_filter: str, seat_class_filter: str | None
) -> tuple[str, str, int] | None:
    trips = page.locator("app-single-trip")
    count = trips.count()
    for i in range(count):
        trip = trips.nth(i)
        name_el = trip.locator(".trip-left-info h2").first
        if name_el.count() == 0:
            continue
        name = name_el.inner_text().strip()
        if train_filter.lower() not in name.lower():
            continue
        seats = trip.locator(".single-seat-class")
        for j in range(seats.count()):
            seat = seats.nth(j)
            cls_el = seat.locator(".seat-class-name").first
            if cls_el.count() == 0:
                continue
            cls_name = cls_el.inner_text().strip()
            if seat_class_filter and cls_name.lower() != seat_class_filter.lower():
                continue
            avail_el = seat.locator(".all-seats").first
            if avail_el.count() == 0:
                continue
            avail_text = avail_el.inner_text().strip()
            available = int(avail_text) if avail_text.isdigit() else 0
            if available <= 0:
                continue
            btn = seat.locator(".book-now-btn").first
            if btn.count() == 0:
                continue
            btn.click()
            return name, cls_name, available
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Automate Chrome with Playwright, log in via the Shohoz token, and open the "
        "Bangladesh Railway eticket search page."
    )
    parser.add_argument("--from", dest="fromcity", default="Dhaka", help="Departure city, e.g. Dhaka")
    parser.add_argument("--to", dest="tocity", default="Chattogram", help="Arrival city, e.g. Chattogram")
    parser.add_argument("--doj", default="14-Aug-2026", help="Date of journey, e.g. 14-Aug-2026")
    parser.add_argument("--class", dest="train_class", default="AC_S", help="Seat class, e.g. AC_S")
    parser.add_argument("--device-key", default=DEVICE_KEY, help="X-Device-Key / localStorage 'ssdk'; defaults to $SSDK")
    parser.add_argument("--device-id", default=DEVICE_ID, help="X-Device-Id / localStorage 'uudid'; defaults to $UUDID")
    parser.add_argument("--headed", action="store_true", help="Run with a visible Chrome window (default: headed)")
    parser.add_argument("--headless", action="store_true", help="Run Chrome headless")
    parser.add_argument("--keep-open", action="store_true", help="Keep the browser open until Enter is pressed")
    parser.add_argument("--dump", action="store_true", help="Parse and print available trips from the rendered page")
    parser.add_argument("--no-login", action="store_true", help="Open the page without injecting the token")
    parser.add_argument("--allow-turnstile", action="store_true", help="Load the real Cloudflare Turnstile captcha (stubbed/blocked by default)")
    parser.add_argument("--debug", action="store_true", help="Log railspaapi API request/response pairs")
    parser.add_argument("--book", action="store_true", help="Click BOOK NOW on the first available seat class of the target train")
    parser.add_argument("--train", default="PARJOTAK EXPRESS (816)", help="Train name filter for --book (substring, case-insensitive)")
    parser.add_argument("--book-seat-class", help="Only book this seat class (e.g. SNIGDHA); otherwise the first available is booked")
    parser.add_argument("--timeout", type=int, default=3000000, help="Wait timeout in ms (default: 30000)")
    args = parser.parse_args()

    if not args.no_login:
        token = os.environ.get("TOKEN")
        if not token:
            print("TOKEN environment variable is not set.", file=sys.stderr)
            print("Export it first:", file=sys.stderr)
            print("  export TOKEN='<from localStorage.getItem(\"token\")>'", file=sys.stderr)
            return 1

    url = build_search_url(args.fromcity, args.tocity, args.doj, args.train_class)
    print(f"Opening: {url}")

    headless = args.headless or not args.headed
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=headless)
        context = browser.new_context(user_agent=USER_AGENT)
        if not args.allow_turnstile:
            context.route("**railspaapi.shohoz.com/**", handle_booking_route)
            context.route("**/handshake", handle_handshake_route)
            context.route("**challenges.cloudflare.com/**", handle_turnstile_route)
        if not args.no_login:
            context.add_init_script(auth_init_script(token, args.device_key, args.device_id))

        page = context.new_page()
        if args.debug:

            def on_api_response(resp) -> None:
                if "railspaapi.shohoz.com" not in resp.url:
                    return
                try:
                    body = resp.text()
                except Exception:
                    body = "<no body>"
                print(f"[API] {resp.status} {resp.request.method} {resp.url[:220]}")
                if resp.status >= 400:
                    print(f"[API]   body: {body[:800]}")

            page.on("response", on_api_response)

        page.goto(url, wait_until="domcontentloaded", timeout=args.timeout)

        if not args.no_login:
            set_local_storage(page, token, args.device_key, args.device_id)
            page.goto(url, wait_until="domcontentloaded", timeout=args.timeout)

            logged_in = is_logged_in(page)
            print(f"Login status: {'logged in' if logged_in else 'NOT logged in'}")
            if not logged_in:
                print("Token was injected but the app may have rejected it (expired/invalid).", file=sys.stderr)
            if "/login" in page.url:
                print("App redirected to /login: the server rejected the token "
                      "(stale/revoked). Get a fresh one and retry.", file=sys.stderr)
            print(f"Final URL: {page.url}")

        try:
            page.wait_for_selector("app-single-trip", timeout=args.timeout)
            print("Search results loaded.")
        except Exception:
            print("No results found yet; the page may still be loading or show an error.", file=sys.stderr)

        if args.dump:
            trips = parse_trips_from_page(page)
            print_trips(trips)

        if args.book:
            result = click_book_now(page, args.train, args.book_seat_class)
            if result:
                train_name, cls_name, available = result
                print(
                    f"Clicked BOOK NOW for {train_name} - {cls_name} "
                    f"({available} seat(s) available)."
                )
                try:
                    page.wait_for_selector("app-seat-layout", timeout=args.timeout)
                    print("Seat layout modal opened.")
                except Exception:
                    try:
                        page.wait_for_url(lambda u: "trip-info" in u, timeout=args.timeout)
                        print(f"Navigated to: {page.url}")
                    except Exception:
                        print("Seat layout modal did not open.", file=sys.stderr)
            else:
                print(
                    f"No available seat on '{args.train}'"
                    + (f" ({args.book_seat_class})" if args.book_seat_class else "")
                    + " to book.",
                    file=sys.stderr,
                )

        if args.keep_open:
            print("Browser is open. Press Enter to close it...")
            input()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
