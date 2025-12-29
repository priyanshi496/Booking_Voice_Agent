import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
from dotenv import load_dotenv

# Ensure we load from the correct path relative to this file
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.local")
load_dotenv(env_path)

logger = logging.getLogger("booking_service")

# Cal.com API Configuration
CAL_COM_API_KEY = os.getenv("CAL_COM_API_KEY")
CAL_COM_API_URL = "https://api.cal.com/v2"

# Your specific Cal.com details
CAL_USERNAME = "harit-ramanuj-rfakbx"
EVENT_TYPE_SLUG = "30min"

def normalize_phone(phone: str) -> str:
    digits = "".join(filter(str.isdigit, phone))
    return f"+91{digits[-10:]}"

def extract_booking_phone(booking: dict) -> str | None:
    # 1️⃣ attendees[].phoneNumber (BEST)
    for attendee in booking.get("attendees", []):
        phone = attendee.get("phoneNumber")
        if phone:
            return phone

    # 2️⃣ bookingFieldsResponses.attendeePhoneNumber
    bfr = booking.get("bookingFieldsResponses", {})
    phone = bfr.get("attendeePhoneNumber")
    if phone:
        return phone

    # 3️⃣ metadata.guest_phone (fallback)
    meta = booking.get("metadata", {})
    return meta.get("guest_phone")

def parse_datetime(date_str: str, time_str: str, timezone: str = "Asia/Kolkata") -> str:
    """
    Parses date and time strings using dateutil for robustness.
    Returns ISO 8601 string: 'YYYY-MM-DDTHH:MM:SS.000Z' in Asia/Kolkata.
    """
    from dateutil import parser
    
    current_tz = ZoneInfo(timezone)
    now_in_tz = datetime.now(current_tz)
    
    # 1. Clean Inputs
    date_clean = date_str.strip() if date_str else ""
    time_clean = time_str.strip() if time_str else ""
    
    if not date_clean:
         # Assume today if no date provided? Or raise.
         target_date = now_in_tz
    else:
        # Special keywords
        if "tomorrow" in date_clean.lower():
            target_date = now_in_tz + timedelta(days=1)
        elif "today" in date_clean.lower():
            target_date = now_in_tz
        else:
             # Use dateutil parser
             try:
                 # default to now to fill in year/month if missing
                 parsed = parser.parse(date_clean, default=now_in_tz, fuzzy=True)
                 target_date = parsed
             except Exception:
                 # Fallback manual parsing if needed, but parser is usually good
                 raise ValueError(f"Could not parse date: {date_str}")
    
    # 2. Parse Time
    if not time_clean:
         raise ValueError("Time argument is missing")
         
    # Handle "5pm" "5.30" etc via dateutil
    # Pre-process time to be friendly (e.g. 5.30 -> 5:30)
    time_input = time_clean.upper().replace(".", ":")
    try:
        # Use a dummy date to parse time efficiently
        time_parsed = parser.parse(time_input, default=now_in_tz)
        target_time = time_parsed.time()
    except Exception:
         # Try logic for "10" -> "10:00"
         if time_input.strip().isdigit():
              try:
                   h = int(time_input.strip())
                   target_time = now_in_tz.replace(hour=h, minute=0).time()
              except:
                   raise ValueError(f"Could not parse time: {time_str}")
         else:
              raise ValueError(f"Could not parse time: {time_str}")

    # Combine
    final_dt_aware = datetime.combine(target_date.date(), target_time, tzinfo=current_tz)
    
    # Check if this led to a past time for today? (Optional logic)
    # if final_dt_aware < now_in_tz: 
    #    final_dt_aware += timedelta(days=1) # Assume next day? No, safer to fail or assume user meant past.

    final_dt_utc = final_dt_aware.astimezone(ZoneInfo("UTC"))
    return final_dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

class BookingService:
    async def _get_event_type_id(self, slug: str) -> int:
        async with httpx.AsyncClient() as client:
            # Try V2 first (Standard Bearer Auth)
            try:
                res = await client.get(
                    "https://api.cal.com/v2/event-types",
                    headers={"Authorization": f"Bearer {CAL_COM_API_KEY}"}
                )
                logger.info(f"V2 Event Types Status: {res.status_code}")
                if res.status_code == 200:
                    data = res.json()
                    items = data.get("data", [])
                    
                    found_slugs = []
                    valid_types = []
                    
                    # Handle V2 Grouped Structure
                    if isinstance(items, dict) and "eventTypeGroups" in items:
                        groups = items["eventTypeGroups"]
                        # groups is likely a list of groups, each containing eventTypes
                        if isinstance(groups, list):
                            for group in groups:
                                event_types = group.get("eventTypes", [])
                                valid_types.extend(event_types)
                    
                    # Direct check if eventTypes is somehow at top level of items dict
                    if isinstance(items, dict) and "eventTypes" in items:
                         valid_types.extend(items["eventTypes"])
                         
                    found_slugs = [t.get("slug") for t in valid_types]
                    logger.info(f"V2 Available Slugs: {found_slugs}")
                    
                    for t in valid_types:
                        if t.get("slug") == slug:
                            return int(t.get("id"))
            except Exception as e:
                logger.warning(f"V2 Event Type Fetch Failed: {e}", exc_info=True)

            # Fallback to V1
            logger.info("Falling back to V1 for Event Types")
            res = await client.get(
                "https://api.cal.com/v1/event-types",
                params={"apiKey": CAL_COM_API_KEY}
            )
            logger.info(f"V1 Event Types Status: {res.status_code}")
            
            found_slugs = []
            if res.status_code == 200:
                types = res.json().get("eventTypes", [])
                found_slugs = [t.get("slug") for t in types if isinstance(t, dict)]
                logger.info(f"V1 Available Slugs: {found_slugs}")
                
                for t in types:
                    if isinstance(t, dict) and t.get("slug") == slug:
                        return t.get("id")
            
            raise ValueError(f"Slug '{slug}' not found. Available: {', '.join(filter(None, found_slugs))}")

    async def create_booking(self, date: str, time: str, guest_phone: str, title: str = "30 Minute Meeting"):
        try:
            start_time = parse_datetime(date, time)
            phone = "+91" + "".join(filter(str.isdigit, guest_phone))[-10:]
            
            # Fetch numeric ID for the slug
            try:
                event_type_id = await self._get_event_type_id(EVENT_TYPE_SLUG)
            except ValueError as ve:
                return False, str(ve)


            # V1 Payload Structure
            payload = {
                "eventTypeId": event_type_id,
                "start": start_time,
                "responses": {
                    "name": "Priyanshi",
                    "email": "guest@voice.ai",
                    "location": {
                        "value": "phone",
                        "optionValue": phone
                    },
                    "attendeePhoneNumber": phone, # Required by some Cal.com event configurations
                    "guest_phone": phone # Fallback convention
                },
                "metadata": {"title": title},
                "timeZone": "Asia/Kolkata",
                "language": "en",
            }

            logger.info(f"Booking Payload: {payload}")

            async with httpx.AsyncClient() as client:
                res = await client.post(
                    f"https://api.cal.com/v1/bookings",
                    headers={
                        "Content-Type": "application/json",
                        "cal-api-version": "2024-08-13",
                    },
                    params={"apiKey": CAL_COM_API_KEY},
                    json=payload,
                )
            
            logger.info(f"Booking Response Status: {res.status_code}")
            logger.info(f"Booking Response Body: {res.text}")

            if res.status_code in (200, 201):
                data = res.json()
                uid = data.get("uid") or data.get("bookings", [{}])[0].get("uid")
                return True, f"Your meeting is confirmed. Reference ID: {uid}"
            return False, f"Unable to book: {res.text}"

        except Exception as e:
            logger.error(f"Booking Error: {e}", exc_info=True)
            return False, f"Booking failed: {str(e)}"

    async def get_availability(self, date_str: str):
        try:
            iso = parse_datetime(date_str, "12:00 PM")
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            formatted_date = dt.strftime("%Y-%m-%d")

            async with httpx.AsyncClient() as client:
                res = await client.get(
                    f"https://api.cal.com/v1/availability",
                    headers={
                        "cal-api-version": "2024-08-13",
                    },
                    params={
                        "apiKey": CAL_COM_API_KEY,
                        "dateFrom": f"{formatted_date}T00:00:00.000Z",
                        "dateTo": f"{formatted_date}T23:59:59.999Z",
                        "username": CAL_USERNAME,
                        "eventTypeSlug": EVENT_TYPE_SLUG,
                    },
                )

            if res.status_code != 200:
                logger.error(f"Availability API error: {res.status_code} - {res.text}")
                return None, f"System error checking availability (Status: {res.status_code})."

            debug_data = res.json()
            
            # Strategy 1: Pre-computed slots (if available)
            days = debug_data.get("days", [])
            slots = []
            if days:
                slots = [s["time"] for s in days[0].get("slots", [])]
            
            # Strategy 2: Calculate from dateRanges (Fallback)
            if not slots and "dateRanges" in debug_data:
                date_ranges = debug_data.get("dateRanges", [])
                for rng in date_ranges:
                    start_str = rng["start"]
                    end_str = rng["end"]
                    # Parse UTC
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    
                    # Generate 30-min slots
                    curr = start_dt
                    while curr + timedelta(minutes=30) <= end_dt:
                        slots.append(curr.isoformat())
                        curr += timedelta(minutes=30)

            if not slots:
                return [], f"No slots available on {formatted_date}."

            times = []
            for s in slots:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                times.append(dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%I:%M %p"))
            
            return times, None

        except Exception as e:
            logger.error(e)
            return None, "Error checking availability."

    async def list_bookings(self, phone_number: str):
        try:
            target_phone = normalize_phone(phone_number)
            logger.info(f"Listing bookings for {target_phone}")

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{CAL_COM_API_URL}/bookings",
                    headers={
                        "Authorization": f"Bearer {CAL_COM_API_KEY}",
                        "cal-api-version": "2024-08-13",
                    },
                    params={"status": "upcoming"},
                    timeout=10.0,
                )
            
            logger.info(f"List Bookings Response: {response.status_code}")

            if response.status_code != 200:
                logger.error(f"List bookings failed: {response.text}")
                return None, "Couldn't access bookings."

            bookings = response.json().get("data", [])
            matched = []
            for booking in bookings:
                booking_phone = extract_booking_phone(booking)
                if booking_phone and normalize_phone(booking_phone) == target_phone:
                    # Format start time for better TTS
                    start_iso = booking.get("start")
                    try:
                        # Assume ISO format
                        dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                        local_dt = dt.astimezone(ZoneInfo("Asia/Kolkata"))
                        # Format: "Friday, December 20 at 10:00 AM"
                        human_readable = local_dt.strftime("%A, %B %d at %I:%M %p")
                        booking["human_start"] = human_readable
                        booking["start_dt"] = local_dt # Store for logic
                    except Exception:
                        booking["human_start"] = start_iso # Fallback
                        
                    matched.append(booking)
            
            logger.info(f"Found {len(matched)} matching bookings")
            return matched, None # Returns list of booking dicts

        except Exception as e:
            logger.error(f"Error checking bookings: {e}", exc_info=True)
            return None, "Error checking bookings."

    async def cancel_booking(self, booking_uid: str, reason: str = "User requested"):
        try:
            logger.info(f"Cancelling booking {booking_uid}")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{CAL_COM_API_URL}/bookings/{booking_uid}/cancel",
                    headers={
                        "Authorization": f"Bearer {CAL_COM_API_KEY}",
                        "cal-api-version": "2024-08-13",
                    },
                    json={"cancellationReason": reason},
                    timeout=10.0,
                )
                
                logger.info(f"Cancel Response: {response.status_code} - {response.text}")
                
                if response.status_code in [200, 201]:
                    return True, "Your appointment has been cancelled successfully."
                else:
                    return False, f"Failed to cancel: {response.text}"
                    
        except Exception as e:
            logger.error(f"Cancel Error: {e}", exc_info=True)
            return False, f"Error: {e}"

    async def reschedule_booking(self, booking_uid: str, new_date: str, new_time: str, guest_phone: str):
        logger.info(f"Rescheduling {booking_uid} to {new_date} {new_time}")
        
        # 1. Create NEW booking first to ensure slot is available
        success, msg = await self.create_booking(new_date, new_time, guest_phone, title="Rescheduled Meeting")
        if not success:
             return False, f"Failed to book new time: {msg}"
        
        # 2. Cancel OLD booking
        cancel_success, cancel_msg = await self.cancel_booking(booking_uid, "Rescheduling to new time")
        if not cancel_success:
             return True, f"New meeting booked, but failed to cancel old one: {cancel_msg}"
             
        return True, "Rescheduled successfully."
