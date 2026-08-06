import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

SEARCH_URL = "https://eticket.railway.gov.bd/booking/train/search"
RESERVE_MARKER = "bookings/reserve-seat"

DEVICE_KEY = os.environ.get(
    "SSDK",
    "7525b9e91c221ec9ac822ccebf0deba676b908ee2f3923d8b9ed8ad879ad595ecffd27592c8e8b679d4759a355c9416ffbf307c8933f5eb587c29f23365f59e664f3b805bddcd74b17ad74b74ead8b03",
)
DEVICE_ID = os.environ.get("UUDID", "adc80545319c3d946cf7ee25cfce5cc5")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


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


def build_search_url(fromcity: str, tocity: str, doj: str, train_class: str) -> str:
    return urlunsplit(
        (
            "https",
            "eticket.railway.gov.bd",
            "/booking/train/search",
            urlencode(
                {
                    "fromcity": fromcity,
                    "tocity": tocity,
                    "doj": doj,
                    "class": train_class,
                },
                quote_via=quote,
            ),
            "",
        )
    )


def url_doj(url: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get("doj")
    return values[0] if values else None


def click_book_now(page, train_filter: str, seat_class_filter: str | None) -> tuple[str, str] | None:
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
            return name, cls_name
    return None


def select_coach_with_seats(page, coach_filter: str | None) -> int | None:
    page.wait_for_selector("#select-bogie", timeout=60000)
    options = page.locator("#select-bogie option")
    count = options.count()
    for i in range(count):
        opt = options.nth(i)
        label = opt.inner_text().strip()
        if coach_filter and coach_filter not in label:
            continue
        match = re.search(r"-\s*(\d+)\s*Seat", label)
        seats = int(match.group(1)) if match else 0
        if seats <= 0:
            continue
        value = opt.get_attribute("value")
        page.select_option("#select-bogie", value=value)
        page.wait_for_timeout(1500)
        avail = page.locator(".btn-seat.seat-available:not(.seat-selected)")
        if avail.count() > 0:
            return i
    return None


def find_available_seat(page, seat_filter: str | None, coach_filter: str | None) -> tuple | None:
    page.wait_for_selector("#select-bogie", timeout=60000000)
    page.wait_for_timeout(2000)
    selected = select_coach_with_seats(page, coach_filter)
    if selected is None:
        return None
    if seat_filter:
        target = page.locator(
            f".btn-seat.seat-available:not(.seat-selected)[title='{seat_filter}']"
        )
        if target.count() == 0:
            return None
        return target.first, seat_filter
    seats = page.locator(".btn-seat.seat-available:not(.seat-selected)")
    count = seats.count()
    for i in range(count):
        seat = seats.nth(i)
        text = seat.inner_text().strip()
        if not text:
            continue
        return seat, text
    return None


def couple_chamber_seats(page) -> list[str] | None:
    rows = page.locator("app-seat-layout .seat-row")
    current: list[str] = []
    current_total = 0
    for i in range(rows.count()):
        row = rows.nth(i)
        real = row.locator(".btn-seat:not(.seat-hidden)")
        if real.count() == 0:
            if current_total == 2 and len(current) == 2:
                return current
            current = []
            current_total = 0
            continue
        current_total += real.count()
        avail = row.locator(".btn-seat.seat-available:not(.seat-selected)")
        for j in range(avail.count()):
            text = avail.nth(j).inner_text().strip()
            if text:
                current.append(text)
    if current_total == 2 and len(current) == 2:
        return current
    return None


def find_couple_chamber(page, coach_filter: str | None) -> list[str] | None:
    page.wait_for_selector("#select-bogie", timeout=60000000)
    options = page.locator("#select-bogie option")
    count = options.count()
    for i in range(count):
        opt = options.nth(i)
        label = opt.inner_text().strip()
        if coach_filter and coach_filter not in label:
            continue
        match = re.search(r"-\s*(\d+)\s*Seat", label)
        seats = int(match.group(1)) if match else 0
        if seats <= 0:
            continue
        value = opt.get_attribute("value")
        page.select_option("#select-bogie", value=value)
        page.wait_for_timeout(1500)
        chamber = couple_chamber_seats(page)
        if chamber:
            return chamber
    return None


def journey_dates(doj: str | None) -> list[str]:
    if doj:
        return [doj]
    today = date.today()
    return [(today + timedelta(days=i)).strftime("%d-%b-%Y") for i in range(11)]


def attempt_booking(
    page,
    args,
    url: str,
    token: str | None,
    attached: bool,
) -> tuple[int, int, list]:
    seats_to_reserve = max(1, min(args.seats, 4))
    turnstile_errors: list[str] = []

    def on_response(resp) -> None:
        if RESERVE_MARKER in resp.url and resp.request.method == "PATCH":
            try:
                body = resp.json()
            except Exception:
                body = {"_raw": (resp.text() if resp.text else "")[:500]}
            print(f"\n[reserve-seat] HTTP {resp.status}")
            print(json.dumps(body, indent=2))

    def on_console(msg) -> None:
        text = msg.text
        if "turnstile" in text.lower() or "600010" in text:
            turnstile_errors.append(text)
            print(f"[turnstile] {text}", file=sys.stderr)

    page.on("response", on_response)
    page.on("console", on_console)

    print(f"Loading: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=args.timeout)
    except Exception as exc:
        print(f"Navigation failed: {exc}", file=sys.stderr)
        return 0, seats_to_reserve, []

    if not attached:
        set_local_storage(page, token or "", args.device_key, args.device_id)
        page.goto(url, wait_until="domcontentloaded", timeout=args.timeout)
    else:
        if not is_logged_in(page):
            if not token:
                print(
                    "Attached Chrome is not logged in and TOKEN env is not set.",
                    file=sys.stderr,
                )
                return 0, seats_to_reserve, []
            set_local_storage(page, token, args.device_key, args.device_id)
            page.goto(url, wait_until="domcontentloaded", timeout=args.timeout)

    if args.doj:
        final_doj = url_doj(page.url)
        if final_doj and final_doj != args.doj:
            print(
                f"Tickets for {args.doj} are not available yet: the site redirected "
                f"the search to {final_doj}.",
                file=sys.stderr,
            )
            return -1, seats_to_reserve, []

    if not is_logged_in(page):
        print("Not logged in: token missing/expired.", file=sys.stderr)
        return 0, seats_to_reserve, []

    try:
        page.wait_for_selector("app-single-trip", timeout=args.timeout)
        print("Search results loaded.")
    except Exception:
        print("No search results appeared.", file=sys.stderr)
        if turnstile_errors:
            print("Turnstile reported errors during page load:", file=sys.stderr)
            for e in turnstile_errors[:5]:
                print(f"  {e}", file=sys.stderr)
        return 0, seats_to_reserve, []

    seat_class = args.seat_class or args.train_class
    result = click_book_now(page, args.train, seat_class)
    if not result:
        print(
            f"No BOOK NOW button found for '{args.train}'"
            + (f" / '{seat_class}'" if seat_class else "")
            + " with available seats.",
            file=sys.stderr,
        )
        return 0, seats_to_reserve, []
    train_name, cls_name = result
    print(f"Clicked BOOK NOW for {train_name} - {cls_name}. Waiting for seat layout...")

    try:
        page.wait_for_selector("app-seat-layout", timeout=args.timeout)
        print("Seat layout opened.")
    except Exception:
        print("Seat layout did not open.", file=sys.stderr)
        if turnstile_errors:
            print("Turnstile reported errors:", file=sys.stderr)
            for e in turnstile_errors[:5]:
                print(f"  {e}", file=sys.stderr)
        print(
            "If you see Cloudflare error 600010, the automated browser fingerprint is being "
            "blocked. Use --cdp-port to drive your real Chrome instead.",
            file=sys.stderr,
        )
        return 0, seats_to_reserve, []

    if args.dump_layout:
        html = page.locator("app-seat-layout").inner_html()
        print("=== SEAT LAYOUT HTML (truncated) ===")
        print(html[:4000])

    planned: list[str] = []
    if seats_to_reserve == 2:
        planned = find_couple_chamber(page, args.coach)
        if not planned:
            print(
                "No private 2-berth chamber (couple cabin) with both seats available "
                "on this date.",
                file=sys.stderr,
            )
            return 0, seats_to_reserve, []
        print(f"Couple chamber found: {', '.join(planned)}")
    else:
        seat_loc = find_available_seat(page, args.seat, args.coach)
        if not seat_loc:
            print(
                "No available seat to click"
                + (f" (tried '{args.seat}')" if args.seat else "")
                + " on this date.",
                file=sys.stderr,
            )
            return 0, seats_to_reserve, []
        planned = [seat_loc[1]]

    reserved: list[dict] = []
    for n in range(seats_to_reserve):
        if n > 0 and len(planned) < seats_to_reserve:
            seat_loc = find_available_seat(page, None, args.coach)
            if not seat_loc:
                print(
                    f"Only {n} of {seats_to_reserve} seat(s) were available.",
                    file=sys.stderr,
                )
                break
            planned.append(seat_loc[1])
        seat_number = planned[n]
        seat_el = page.locator(f".btn-seat[title='{seat_number}']")
        if seat_el.count() == 0:
            print(
                f"Seat {seat_number} is not in the seat layout anymore.",
                file=sys.stderr,
            )
            break
        print(f"Clicking seat {seat_number} ({n+1}/{seats_to_reserve})...")

        try:
            with page.expect_response(
                lambda r: RESERVE_MARKER in r.url and r.request.method == "PATCH",
                timeout=args.timeout,
            ) as resp_info:
                seat_el.first.click()
            resp = resp_info.value
        except Exception as exc:
            print(f"No reserve-seat response: {exc}", file=sys.stderr)
            if turnstile_errors:
                print("Turnstile reported errors:", file=sys.stderr)
                for e in turnstile_errors[:5]:
                    print(f"  {e}", file=sys.stderr)
            break

        try:
            body = resp.json()
        except Exception:
            body = None
        print(f"[reserve-seat] HTTP {resp.status}")
        print(json.dumps(body, indent=2) if body is not None else resp.text()[:500])

        ok = isinstance(body, dict) and isinstance(body.get("data"), dict) and body["data"].get("ack") == 1
        reserved.append({"seat": seat_number, "success": ok, "body": body})
        if ok:
            print(
                f"\nSUCCESS: {body['data'].get('message', 'Reserved!')} - seat {seat_number}"
            )
        else:
            print(f"\nSeat {seat_number} did not reserve; see response above.", file=sys.stderr)

    ok_count = sum(1 for r in reserved if r["success"])
    print(f"\nReserved {ok_count}/{len(reserved)} seat(s): {[r['seat'] for r in reserved]}")

    if ok_count > 0 and args.do_continue:
        print("Clicking CONTINUE PURCHASE...")
        try:
            continue_btn = page.locator("#confirmbooking .continue-btn")
            if continue_btn.count() == 0:
                continue_btn = page.locator(".continue-btn")
            if continue_btn.count() == 0:
                print("CONTINUE PURCHASE button not found.", file=sys.stderr)
            else:
                with page.expect_navigation(timeout=args.timeout) as nav_info:
                    continue_btn.first.click()
                nav_info.value
                print(f"Navigated to: {page.url}")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=args.timeout)
                except Exception:
                    pass
                print("CONTINUE PURCHASE clicked.")
        except Exception as exc:
            print(f"Error clicking CONTINUE PURCHASE: {exc}", file=sys.stderr)

    return ok_count, seats_to_reserve, reserved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reserve a Bangladesh Railway seat in a real browser (handles the "
        "Cloudflare Turnstile cft_response automatically)."
    )
    parser.add_argument("--from", dest="fromcity", default="Dhaka", help="Departure city")
    parser.add_argument("--to", dest="tocity", default="Cox's Bazar", help="Arrival city")
    parser.add_argument(
        "--doj",
        default=None,
        help="Date of journey, e.g. 11-Aug-2026. Omit to try the next 11 days from today.",
    )
    parser.add_argument("--class", dest="train_class", default="AC_B", help="Seat class (default: AC_B)")
    parser.add_argument(
        "--train",
        default="COXS BAZAR EXPRESS (814)",
        help="Train name filter (substring); 'all' for every train",
    )
    parser.add_argument("--seat-class", help="Only book this seat class (defaults to --class)")
    parser.add_argument("--seat", help="Reserve this exact seat number (e.g. JHA-1)")
    parser.add_argument(
        "--seats",
        type=int,
        default=1,
        help="Number of seats to reserve (1-4, default: 1). With 2, both seats are "
        "taken from a single private 2-berth chamber (couple cabin).",
    )
    parser.add_argument("--coach", help="Switch to this coach (e.g. GA); otherwise the first coach with seats is used")
    parser.add_argument("--device-key", default=DEVICE_KEY, help="X-Device-Key / localStorage 'ssdk'")
    parser.add_argument("--device-id", default=DEVICE_ID, help="X-Device-Id / localStorage 'uudid'")
    parser.add_argument("--headless", action="store_true", help="Run Chrome headless (Turnstile may fail; keep headed)")
    parser.add_argument(
        "--cdp-port",
        type=int,
        default=0,
        help="Attach to a real Chrome started with --remote-debugging-port=<port> instead of launching a new one. "
        "This passes Turnstile reliably.",
    )
    parser.add_argument("--dump-layout", action="store_true", help="Print the seat layout HTML after it loads")
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep the browser window open (with an optional timeout) instead of closing it",
    )
    parser.add_argument(
        "--keep-timeout",
        type=int,
        default=0,
        help="Seconds to keep the browser open before closing (0 = keep forever until Ctrl+C)",
    )
    parser.add_argument(
        "--continue",
        dest="do_continue",
        action="store_true",
        help="Click CONTINUE PURCHASE after reserving (default: do not click it)",
    )
    parser.add_argument("--timeout", type=int, default=120000, help="Wait timeout in ms")
    parser.add_argument(
        "--retry-interval",
        type=int,
        default=3,
        help="Seconds to wait between retries when the requested date is not yet "
        "available for booking",
    )
    args = parser.parse_args()

    dates = journey_dates(args.doj)
    print(f"Will try {len(dates)} date(s): {', '.join(dates)}")

    with sync_playwright() as p:
        attached = False

        def close_browser(keep_page=None) -> None:
            if args.keep_open and keep_page is not None:
                if args.keep_timeout and args.keep_timeout > 0:
                    print(
                        f"Keeping the browser open for {args.keep_timeout}s... "
                        "(Ctrl+C to close early)",
                        file=sys.stderr,
                    )
                else:
                    print("Keeping the browser open... (Ctrl+C to close)", file=sys.stderr)
                try:
                    start = time.monotonic()
                    while True:
                        if (
                            args.keep_timeout
                            and args.keep_timeout > 0
                            and time.monotonic() - start >= args.keep_timeout
                        ):
                            break
                        keep_page.wait_for_timeout(1000)
                except KeyboardInterrupt:
                    pass
            if attached:
                if keep_page is not None:
                    try:
                        keep_page.close()
                    except Exception:
                        pass
            else:
                browser.close()

        if args.cdp_port:
            try:
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{args.cdp_port}")
                attached = True
                print(f"Attached to Chrome on port {args.cdp_port}.")
            except Exception as exc:
                print(
                    f"Could not connect to Chrome on port {args.cdp_port}: {exc}",
                    file=sys.stderr,
                )
                print(
                    "Start Chrome first:\n"
                    "  osascript -e 'quit app \"Google Chrome\"' && \\\n"
                    "  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222",
                    file=sys.stderr,
                )
                return 1
            context = browser.contexts[0]
        else:
            browser = p.chromium.launch(
                channel="chrome",
                headless=args.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(user_agent=USER_AGENT)
            context.add_init_script(STEALTH_JS)

        token = os.environ.get("TOKEN")
        if not attached:
            token = token_for(token)

        active_page = None
        for doj in dates:
            print(f"\n=== Trying {doj} ===")
            while True:
                page = context.new_page()
                url = build_search_url(args.fromcity, args.tocity, doj, args.train_class)
                ok_count, seats_to_reserve, _ = attempt_booking(page, args, url, token, attached)
                if ok_count < 0:
                    try:
                        page.close()
                    except Exception:
                        pass
                    print(
                        f"Tickets for {doj} are not yet available; retrying in "
                        f"{args.retry_interval}s... (Ctrl+C to stop)",
                        file=sys.stderr,
                    )
                    time.sleep(args.retry_interval)
                    continue
                if ok_count == seats_to_reserve and seats_to_reserve > 0:
                    active_page = page
                    print(f"\nSuccess on {doj}. Keeping this tab.")
                    break
                print(f"No successful booking on {doj}.", file=sys.stderr)
                try:
                    page.close()
                except Exception:
                    pass
                break
            if active_page is not None:
                break

        if active_page is None:
            print("Could not book on any of the tried dates.", file=sys.stderr)
            close_browser()
            return 1

        close_browser(active_page)
    return 0


def token_for(env: str | None) -> str:
    if not env:
        print("TOKEN environment variable is not set.", file=sys.stderr)
        print("Export it first:", file=sys.stderr)
        print("  export TOKEN='<from localStorage.getItem(\"token\")>'", file=sys.stderr)
        sys.exit(1)
    return env


if __name__ == "__main__":
    sys.exit(main())
