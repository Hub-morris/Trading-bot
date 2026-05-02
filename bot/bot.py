import base64
import json
import os
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import websocket

# --- OAuth configuration ---
OAUTH_CLIENT_ID = os.getenv("DERIV_OAUTH_CLIENT_ID", "<YOUR_CLIENT_ID>")
OAUTH_CLIENT_SECRET = os.getenv("DERIV_OAUTH_CLIENT_SECRET", "<YOUR_CLIENT_SECRET>")
REDIRECT_URI = os.getenv("DERIV_REDIRECT_URI", "http://localhost:5000/callback")
DERIV_ENV = os.getenv("DERIV_ENV", "development").lower()
OAUTH_SCOPE = "trade account_management"
AUTH_URL = "https://oauth.deriv.com/oauth2/authorize"
TOKEN_URL = "https://oauth.deriv.com/oauth2/token"

# --- Deriv Websocket configuration ---
APP_ID = os.getenv("DERIV_APP_ID", "1089")
SYMBOL = os.getenv("DERIV_SYMBOL", "R_100")  # Deriv synthetic index
CANDLES = []
MAX_CANDLES = 50
ws_url = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"

# --- Strategy configuration ---
STRATEGY_NAME = "liquidity_trap"
ZONE_CANDLE_COUNT = 5
ZONE_TOLERANCE = 0.2

# --- OAuth state storage ---
oauth_result = {"code": None, "error": None}

def build_authorization_url():
    params = {
        "response_type": "code",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": OAUTH_SCOPE,
        "state": "deriv_local_auth",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        query = urllib.parse.parse_qs(parsed.query)
        if "error" in query:
            oauth_result["error"] = query.get("error_description", query["error"])[0]
        elif "code" in query:
            oauth_result["code"] = query["code"][0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Authorization complete.</h1><p>You can close this window and return to the bot.</p></body></html>")

    def log_message(self, format, *args):
        return


def run_local_server():
    server = HTTPServer(("", 5000), OAuthCallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def request_access_token(code: str) -> str | None:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": OAUTH_CLIENT_SECRET,
    }
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(TOKEN_URL, data=body)
    credentials = base64.b64encode(f"{OAUTH_CLIENT_ID}:{OAUTH_CLIENT_SECRET}".encode()).decode()
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_data = json.loads(resp.read().decode())
            return response_data.get("access_token")
    except Exception as exc:
        print("Failed to exchange code for token:", exc)
        return None


def get_oauth_token() -> str | None:
    if OAUTH_CLIENT_ID.startswith("<") or OAUTH_CLIENT_SECRET.startswith("<"):
        print("Please set DERIV_OAUTH_CLIENT_ID and DERIV_OAUTH_CLIENT_SECRET, or replace the placeholders in bot.py.")
        print(f"Redirect URI must be registered in Deriv to match: {REDIRECT_URI}")
        return None

    if not REDIRECT_URI:
        print("DERIV_REDIRECT_URI is not set.")
        return None

    if DERIV_ENV == "production" and REDIRECT_URI.startswith("http://localhost"):
        print("Production deployment requires a public redirect URI.")
        print("Set DERIV_REDIRECT_URI to your live callback URL and register it in Deriv.")
        return None

    server = run_local_server()
    auth_url = build_authorization_url()
    print("Opening browser for OAuth login...")
    print("If the browser does not open automatically, visit this URL:")
    print(auth_url)
    webbrowser.open(auth_url)

    while oauth_result["code"] is None and oauth_result["error"] is None:
        pass

    server.shutdown()

    if oauth_result["error"]:
        print("OAuth authorization failed:", oauth_result["error"])
        return None

    print("Authorization code received, requesting access token...")
    return request_access_token(oauth_result["code"])


# --- Strategy helpers ---
def equal_highs(data):
    zone = data[-(ZONE_CANDLE_COUNT + 1):-1] if len(data) >= ZONE_CANDLE_COUNT + 1 else data[-ZONE_CANDLE_COUNT:]
    highs = [c["high"] for c in zone]
    return max(highs) - min(highs) < ZONE_TOLERANCE


def equal_lows(data):
    zone = data[-(ZONE_CANDLE_COUNT + 1):-1] if len(data) >= ZONE_CANDLE_COUNT + 1 else data[-ZONE_CANDLE_COUNT:]
    lows = [c["low"] for c in zone]
    return max(lows) - min(lows) < ZONE_TOLERANCE


def find_trade_signal(data):
    if len(data) < 6:
        return None

    last = data[-1]
    zone = data[-6:-1]
    highs_zone = max(c["high"] for c in zone)
    lows_zone = min(c["low"] for c in zone)

    if equal_highs(data) and last["high"] > highs_zone and last["close"] < highs_zone:
        return "PUT"

    if equal_lows(data) and last["low"] < lows_zone and last["close"] > lows_zone:
        return "CALL"

    return None


def check_trade(ws):
    global CANDLES
    signal = find_trade_signal(CANDLES)
    if signal:
        place_trade(ws, signal)


def place_trade(ws, direction):
    trade = {
        "buy": 1,
        "price": 1,
        "parameters": {
            "amount": 1,
            "basis": "stake",
            "contract_type": direction,
            "currency": "USD",
            "duration": 1,
            "duration_unit": "m",
            "symbol": SYMBOL,
        },
    }
    ws.send(json.dumps(trade))
    print(f"Trade placed: {direction}")


def on_open(ws):
    print("WebSocket opened, authorizing with OAuth access token...")
    ws.send(json.dumps({"authorize": API_TOKEN}))


def subscribe_to_candles(ws):
    print("Authorized. Subscribing to candles...")
    ws.send(json.dumps({
        "ticks_history": SYMBOL,
        "adjust_start_time": 1,
        "count": MAX_CANDLES,
        "end": "latest",
        "granularity": 60,
        "subscribe": 1,
    }))


def on_message(ws, message):
    global CANDLES
    data = json.loads(message)
    print("Received message:", data)

    if data.get("msg_type") == "authorize":
        if "error" in data:
            print("Authorization failed:", data["error"])
            return
        subscribe_to_candles(ws)
        return

    if "error" in data:
        print("API error:", data["error"])
        return

    if "candles" in data:
        CANDLES = data["candles"]

    if "ohlc" in data:
        CANDLES.append(data["ohlc"])
        if len(CANDLES) > MAX_CANDLES:
            CANDLES.pop(0)
        check_trade(ws)


def on_error(ws, error):
    print("WebSocket error:", error)


def on_close(ws, close_status_code, close_msg):
    print("WebSocket closed:", close_status_code, close_msg)


if __name__ == "__main__":
    print("Starting bot...")
    print("Strategy:", STRATEGY_NAME)
    token = get_oauth_token()
    if not token:
        print("Unable to obtain OAuth access token.")
        exit(1)

    API_TOKEN = token
    ws = websocket.WebSocketApp(
        ws_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws.run_forever()
