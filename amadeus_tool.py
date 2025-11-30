import os
import requests
import logging
#from google.adk.tools import tool
logger = logging.getLogger(__name__)
# Amadeus API credentials from environment variables
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")

# Amadeus API endpoints (using the test environment)
TOKEN_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
FLIGHT_OFFERS_URL = "https://test.api.amadeus.com/v2/shopping/flight-offers"
HOTEL_LIST_URL = "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-city"
HOTEL_OFFERS_URL_PRICING = "https://test.api.amadeus.com/v3/shopping/hotel-offers"


def _get_amadeus_token():
    """
    Internal function to fetch an OAuth2 token from the Amadeus API.
    This should not be exposed as a tool to the agent.
    """
    if not AMADEUS_API_KEY or not AMADEUS_API_SECRET:
        return "Error: Amadeus API Key or Secret is not set in environment variables."

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET,
    }
    try:
        response = requests.post(TOKEN_URL, headers=headers, data=data)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        return response.json().get("access_token")
    except requests.exceptions.RequestException as e:
        return f"Error fetching Amadeus token: {e}"

def search_amadeus_flights(
    origin_location_code: str,
    destination_location_code: str,
    departure_date: str,
    adults: int,
    non_stop: bool = False,
    return_date: str = None,
    children: int = 0,
    infants: int = 0,
    travel_class: str = None,
    max_results: int = 3,
) -> str:
    """
    Searches for flight offers using the Amadeus API.

    Args:
        origin_location_code: IATA code for the origin airport (e.g., 'LHR').
        destination_location_code: IATA code for the destination airport (e.g., 'TYO').
        departure_date: The departure date in YYYY-MM-DD format.
        adults: The number of adult passengers.
        non_stop: Whether to search for non-stop flights only.
        return_date: The return date in YYYY-MM-DD format for round-trip flights.
        children: The number of child passengers.
        infants: The number of infant passengers.
        travel_class: The travel class (e.g., 'ECONOMY', 'BUSINESS').
        max_results: The maximum number of flight options to return.
    """
    token = _get_amadeus_token()
    if "Error" in token:
        return token

    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": origin_location_code,
        "destinationLocationCode": destination_location_code,
        "departureDate": departure_date,
        "adults": adults,
        "nonStop": str(non_stop).lower(),  # Convert Python boolean to lowercase string "true" or "false"
        "max": max_results,
    }

    # Add optional parameters to the request if they are provided
    if return_date:
        params["returnDate"] = return_date
    if children > 0:
        params["children"] = children
    if infants > 0:
        params["infants"] = infants
    if travel_class:
        # Ensure travel_class is one of the accepted values by Amadeus
        if travel_class.upper() in ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"]:
            params["travelClass"] = travel_class.upper()

    try:
        response = requests.get(FLIGHT_OFFERS_URL, headers=headers, params=params)
        response.raise_for_status()
        return str(response.json())  # Return the flight data as a string
    except requests.exceptions.RequestException as e:
        # If the request fails, return the detailed error from the API response body.
        if e.response is not None:
            return f"Error from Amadeus API: {e.response.text}"
        return f"Error fetching flight offers: {e}"


def search_amadeus_hotels(
    city_code: str,
    check_in_date: str,
    check_out_date: str,
    adults: int,
    use_test_env: bool = True,
    radius_km: int = 1000,
    max_hotels: int = 5,
    currency: str = "EUR",
    price_range: str = "1-10000",   # set "" to omit
    room_quantity: int = 1,
    view: str = ""                  # e.g., "FULL"; set "" to omit
) -> dict:
    """
    Two-step Amadeus hotel search:
      1) Get hotel IDs by city (IATA city code, e.g., PAR).
      2) Get live offers for those hotel IDs for the given dates.

    Returns a JSON-serializable dict; on error includes {"error": "...", "step": ...}.
    """
    base = "https://test.api.amadeus.com" if use_test_env else "https://api.amadeus.com"
    TOKEN_URL = f"{base}/v1/security/oauth2/token"
    HOTEL_LIST_URL = f"{base}/v1/reference-data/locations/hotels/by-city"
    HOTEL_OFFERS_URL = f"{base}/v3/shopping/hotel-offers"
    TIMEOUT = 20

    # --- AUTH ---
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET,
    }
    try:
        token_resp = requests.post(TOKEN_URL, headers=headers, data=data, timeout=TIMEOUT)
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        if not access_token:
            return {"error": "No access_token in token response", "details": token_resp.text, "step": "auth"}
    except requests.exceptions.RequestException as e:
        details = getattr(e, "response", None).text if getattr(e, "response", None) else str(e)
        return {"error": "Amadeus authentication failed", "details": details, "step": "auth"}

    auth_headers = {"Authorization": f"Bearer {access_token}"}

    # --- STEP 1: Hotel IDs by city ---
    list_params = {"cityCode": city_code, "radius": radius_km, "radiusUnit": "KM"}
    try:
        list_resp = requests.get(HOTEL_LIST_URL, headers=auth_headers, params=list_params, timeout=TIMEOUT)
        list_resp.raise_for_status()
        hotels_data = list_resp.json().get("data", [])
        hotel_ids = [h.get("hotelId") for h in hotels_data if h.get("hotelId")][:max_hotels]
    except requests.exceptions.RequestException as e:
        details = getattr(e, "response", None).text if getattr(e, "response", None) else str(e)
        return {"error": "Hotel List API error", "details": details, "step": 1}
    except (ValueError, KeyError, TypeError) as e:
        return {"error": f"Could not parse hotel IDs: {e}", "step": 1}

    if not hotel_ids:
        return {"error": f"No hotels found in {city_code}. Check city code or increase radius.", "step": 1}

    # --- STEP 2: Offers for those hotels ---

    offer_params = {
        "hotelIds": ",".join(hotel_ids),
        "checkInDate": check_in_date,
        "checkOutDate": check_out_date,
        "adults": adults,
        "roomQuantity": room_quantity,
        # Temporarily relax filters in TEST:
        "includeClosed": "true",     # show closed/fully booked; helps prototyping
        "bestRateOnly": "false",     # don't filter to best rate
        # Omit priceRange/currency first; add later if you see data
        # "currency": currency,
        "priceRange": price_range,
        # Optional richer payload:
        "view": "FULL"
    }
    if currency:
        offer_params["currency"] = currency
    if price_range:
        offer_params["priceRange"] = price_range
    if view:
        offer_params["view"] = view  # e.g., "FULL"

    try:
        offer_resp = requests.get(HOTEL_OFFERS_URL, headers=auth_headers, params=offer_params, timeout=TIMEOUT)
        offer_resp.raise_for_status()
        # Ensure JSON-serializable dict
        return offer_resp.json()
    except requests.exceptions.RequestException as e:
        details = getattr(e, "response", None).text if getattr(e, "response", None) else str(e)
        return {"error": "Hotel Offers API error", "details": details, "step": 2}
