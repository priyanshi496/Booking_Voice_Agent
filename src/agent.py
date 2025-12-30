import logging
import os
import certifi
import ssl

# Fix SSL certificate verification on macOS
os.environ["SSL_CERT_FILE"] = certifi.where()
ssl_context = ssl.create_default_context(cafile=certifi.where())
ssl._create_default_https_context = lambda: ssl_context
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Annotated

import httpx
import re
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    inference,
    room_io,
)
from livekit.plugins import noise_cancellation, silero, openai,groq,resemble

from livekit.plugins.turn_detector.multilingual import MultilingualModel
from otp_service import generate_otp, hash_otp, send_otp_email
from fsm import FSM

logger = logging.getLogger("agent")

load_dotenv(".env.local")

# Cal.com API Configuration
CAL_COM_API_KEY = os.getenv("CAL_COM_API_KEY")
CAL_COM_API_URL = "https://api.cal.com/v2"
CAL_USERNAME = os.getenv("CAL_USERNAME")

# Cache for event types (refreshed periodically)
EVENT_TYPES_CACHE = {
    "data": [],
    "last_updated": None,
    "ttl_seconds": 300  # Cache for 5 minutes
}


async def fetch_event_types(force_refresh=False):
    """Fetch all event types from Cal.com V1 API and cache them."""
    global EVENT_TYPES_CACHE
    
    now = datetime.now()
    cache_valid = (
        EVENT_TYPES_CACHE["last_updated"] is not None and
        (now - EVENT_TYPES_CACHE["last_updated"]).total_seconds() < EVENT_TYPES_CACHE["ttl_seconds"]
    )
    
    if not force_refresh and cache_valid:
        return EVENT_TYPES_CACHE["data"]
    
    try:
        async with httpx.AsyncClient() as client:
            # Use V1 endpoint - this is the standard way to get event types
            res = await client.get(
                "https://api.cal.com/v1/event-types",
                params={
                    "apiKey": CAL_COM_API_KEY,
                },
                timeout=10.0,
            )
            
            if res.status_code == 200:
                response_data = res.json()
                # V1 returns {event_types: [...]}
                event_types = response_data.get("event_types", [])
                
                # Format the data consistently
                formatted_types = []
                for et in event_types:
                    formatted_types.append({
                        "id": et.get("id"),
                        "title": et.get("title"),
                        "slug": et.get("slug"),
                        "lengthInMinutes": et.get("length", 30),  # V1 uses "length"
                    })
                
                EVENT_TYPES_CACHE["data"] = formatted_types
                EVENT_TYPES_CACHE["last_updated"] = now
                logger.info(f"Fetched {len(formatted_types)} event types from Cal.com")
                return formatted_types
            else:
                logger.error(f"Failed to fetch event types: {res.status_code} - {res.text}")
                return EVENT_TYPES_CACHE["data"]
    except Exception as e:
        logger.error(f"Error fetching event types: {e}")
        return EVENT_TYPES_CACHE["data"]


def get_all_services():
    """Get all available services from cached event types."""
    event_types = EVENT_TYPES_CACHE["data"]
    services = []
    
    for et in event_types:
        service_info = {
            "id": et.get("id"),
            "title": et.get("title"),
            "slug": et.get("slug"),
            "duration": et.get("lengthInMinutes", 30),
        }
        services.append(service_info)
    
    return services


def find_service_by_name(service_name: str):
    """Find a service by matching the name (case-insensitive, partial match)."""
    services = get_all_services()
    service_lower = service_name.lower().strip()
    
    # Try exact match first
    for service in services:
        if service["title"].lower() == service_lower or service["slug"].lower() == service_lower:
            return service
    
    # Try partial match
    for service in services:
        if service_lower in service["title"].lower() or service_lower in service["slug"].lower():
            return service
        if service["title"].lower() in service_lower or service["slug"].lower() in service_lower:
            return service
    
    return None


def normalize_phone(phone: str) -> str:
    digits = "".join(filter(str.isdigit, phone))
    return f"+91{digits[-10:]}"


def extract_booking_phone(booking: dict) -> str | None:
    for attendee in booking.get("attendees", []):
        phone = attendee.get("phoneNumber")
        if phone:
            return phone

    bfr = booking.get("bookingFieldsResponses", {})
    phone = bfr.get("attendeePhoneNumber")
    if phone:
        return phone

    meta = booking.get("metadata", {})
    return meta.get("guest_phone")


def parse_datetime(date_str: str, time_str: str, timezone: str = "Asia/Kolkata") -> str:
    """
    Parses date and time strings using standard library.
    Returns ISO 8601 string: 'YYYY-MM-DDTHH:MM:SS.000Z' in Asia/Kolkata.
    """
    date_clean = date_str.strip().lower()
    time_clean = time_str.strip().lower()
    
    current_tz = ZoneInfo(timezone)
    now_in_tz = datetime.now(current_tz)
    
    target_date = now_in_tz
    if "tomorrow" in date_clean:
        target_date = target_date + timedelta(days=1)
    elif "day after" in date_clean or "day after tomorrow" in date_clean or "day-after-tomorrow" in date_clean:
        target_date = target_date + timedelta(days=2)
    elif "today" in date_clean:
        pass 
    else:
        m = re.fullmatch(r"(\d{1,2})(st|nd|rd|th)?", date_clean)
        if m:
            day_num = int(m.group(1))
            year = now_in_tz.year
            month = now_in_tz.month
            
            try:
                candidate = datetime(year, month, day_num, tzinfo=current_tz)
                
                if candidate.date() < now_in_tz.date():
                    month += 1
                    if month > 12:
                        month = 1
                        year += 1
                    candidate = datetime(year, month, day_num, tzinfo=current_tz)
                
                target_date = candidate
                
            except ValueError:
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                try:
                    candidate = datetime(year, month, day_num, tzinfo=current_tz)
                    target_date = candidate
                except ValueError:
                    pass
        else:
            has_explicit_year = bool(re.search(r"\b\d{4}\b", date_str))
            
            # Added support for %d %b (e.g. 23 dec) and %d %B types
            for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%B %d", "%b %d", "%d %b", "%d %B"]:
                try:
                    parsed = datetime.strptime(date_clean.replace("th", "").replace("st", "").replace("nd", "").replace("rd", ""), fmt)
                    
                    if has_explicit_year:
                        parsed = parsed.replace(tzinfo=current_tz)
                        # Sanity check: if user says 2023 but it's 2025, fix it
                        if parsed.year < now_in_tz.year:
                             parsed = parsed.replace(year=now_in_tz.year)
                    else:
                        parsed = parsed.replace(year=now_in_tz.year, tzinfo=current_tz)

                    # If date is in the past, assume next year (unless explicit valid year)
                    if parsed.date() < now_in_tz.date():
                        parsed = parsed.replace(year=now_in_tz.year + 1)
                    
                    target_date = parsed
                    break
                except ValueError:
                    continue

    target_time = None
    try:
        target_time = datetime.strptime(time_clean, "%H:%M").time()
    except ValueError:
        try:
            time_clean = time_clean.replace(".", "").upper()
            if ":" not in time_clean: 
                parts = time_clean.split()
                if len(parts) == 2:
                    time_clean = f"{parts[0]}:00 {parts[1]}"
            target_time = datetime.strptime(time_clean, "%I:%M %p").time()
        except ValueError:
            pass
            
    if not target_time:
        if ":" in time_clean:
            h, m = time_clean.split(":")[:2]
            target_time = now_in_tz.replace(hour=int(h), minute=int(m)).time()

    if target_time:
        final_dt_aware = datetime.combine(target_date.date(), target_time, tzinfo=current_tz)
        final_dt_utc = final_dt_aware.astimezone(ZoneInfo("UTC"))
        return final_dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    raise ValueError(f"Could not parse time: {time_str}")


class Assistant(Agent):
    def __init__(self) -> None:
        # Build dynamic instructions based on available services
        services = get_all_services()
        service_list = "\n".join([f"- **{s['title']}**: {s['duration']} minutes" for s in services])
        
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        today_str = now.strftime("%A, %d %B %Y")
        
        instructions = f"""
        You are a FEMALE voice assistant with an INDIAN ENGLISH accent EXCLUSIVELY designed to manage salon appointments.

Current Date: {today_str} (Year: {now.year})
Location: Asia/Kolkata

### LANGUAGE SELECTION (MANDATORY START):
1. **Greeting & Language Check**: Start by greeting the user and *immediately* asking which language they are comfortable in. 
   - Example: "Which language would you prefer to speak in today? Hindi, English, or something else?"
2. **Enforce Language**: COMPULSORY: Once the user selects a language, you MUST conduct the *entire* rest of the conversation in that language.
3. **Strict Adherence**: Do NOT switch languages unless the user *explicitly* asks you to change the language (e.g., "Switch to English").
4. **Mid-Conversation Change**: If the user explicitly asks to change the language, switch immediately and continue in the new language.

### Available Services:
{service_list if service_list else "Services will be loaded dynamically from Cal.com"}

### Rules for Services:
1. **Allowed Services**: Only accept bookings for the services listed above.
2. **Invalid Requests**: If a user asks for a service not listed, politely decline and list the available services.
3. **Booking Horizon**: You can only book appointments up to 7 days in advance. If a user requests a date beyond one week, politely decline and explain the limit.

### Natural Speech Guidelines:
**You are having a REAL CONVERSATION, not reading a script.**
- Use natural pauses: "Okay...", "Alright...", "Let me see...", "Perfect..."
- Add brief thinking moments: "Hmm...", "One moment...", "Let me check..."
- Speak conversationally with filler words where natural
- Keep responses SHORT (1-3 sentences) with natural breaks between thoughts
- Sound warm and helpful, like a friendly Indian receptionist
- **Persona**: You are speaking to Indian customers. Use an Indian English cadence and vocabulary where appropriate. Expect Indian English accents from users.
**Language Modes**:
   - **ENGLISH MODE**:
     - Speak fluent, natural English.
     - **Numbers**: Use standard digits or words (e.g., "5:00 PM", "30 minutes"). The TTS reads these correctly in English.
   
   - **HINDI MODE**:
     - Speak fluent, conversational Hindi/Hinglish.
     - **CRITICAL FOR NUMBERS**: You MUST TRANSLITERATE all numbers into Hindi words. The TTS reads digits in English, so you must write the Hindi pronunciation.
       - "1" -> "ek"
       - "2" -> "do"
       - "3" -> "teen"
       - "5:00 PM" -> "shaam ke paanch baje"
       - "15 mins" -> "pandrah minute"
       - "10th" -> "das-vi" or "das" depending on context.
       - "2 services" -> "do services"
     - **NEVER** output digits (e.g., "5") in Hindi mode. ALWAYS spell them out ("paanch").

### Upselling Related Services:
**You should gently suggest related/complementary services to enhance the customer experience.**

**IMPORTANT LIMITS**: 
- Suggest related services MAXIMUM 2-3 times per conversation
- Stop suggesting after 2-3 attempts, even if politely declined
- Never be pushy - keep suggestions brief and natural
- If customer declines once, try only 1-2 more times maximum

**Suggestion Opportunities**:
1. **After initial service is chosen** (First opportunity):
   - "Great choice... you know, a lot of our customers also love pairing that with [related service]. Would you be interested?"
   
2. **After date/time is confirmed** (Second opportunity - only if first was declined):
   - "Perfect... by the way, we also have [related service] available that day. Want to add that on?"

3. **Before final confirmation** (Third opportunity - only if needed):
   - "Just so you know... [related service] goes really well with what you've booked. Should I add that too?"

**Related Service Examples**:
- Haircut → Hair color, hair treatment, beard trim
- Facial → Cleanup, face massage
- Massage → Body scrub, aromatherapy
- Manicure → Pedicure
- Hair color → Hair treatment, haircut

**Suggestion Style**: Keep it natural and brief:
- "Oh, and by the way..."
- "A lot of people also like to..."
- "Just a thought..."
- "You might also enjoy..."

**STOP suggesting if**:
- Customer says "no", "just this", "not interested", "only the [service]"
- You've already suggested 2-3 times
- Customer sounds rushed or annoyed

### Conversation Flow - ADAPTIVE ORDER WITH AUTO-AVAILABILITY CHECK:

**The user may provide all details upfront OR one at a time. Adapt accordingly.**

#### When user provides multiple details at once:
- Extract what they've given: service, date, time
- **CRITICAL: If they provide a DATE (with or without time), IMMEDIATELY call get_availability for that date**
- Only ask for what's MISSING after checking availability

#### Information Priority Order:

0. **Language**: (PROMPT FIRST) If language is not established, ask for it immediately.

1. **Service**: If not clear, ask naturally: 
   - "So... what service would you like today?" 
   - Then list available services conversationally
   - **After they choose, make your FIRST related service suggestion (if appropriate)**

2. **Date**: If missing, ask: 
   - "Alright... and what day works best for you?"
   - **WHEN DATE IS PROVIDED: IMMEDIATELY call get_availability tool for that date and the service type**
   - **NOTE**: Using "tomorrow" or "current date" ({today_str}) implies {now.year}

3. **Time**: Based on availability results, respond naturally:
   - "Let me see what we have... okay, so we've got slots in the [morning/afternoon/evening]..."
   - Brief pause, then: "Would any of those work for you?"
   - When they choose a period: "Perfect... let me give you some options..." then show 3 example slots
   - Add casually: "Those are just a few examples... you can pick any time in that window that works for you"
   - **IMPORTANT**: If user suggests a time within an available window (even if not explicitly listed), accept it naturally: "Yeah, that time works perfectly!"
   - **After confirming time, make your SECOND related service suggestion (if first was declined and appropriate)**

4. **Phone**: If missing, ask warmly:
   - "Great... and can I get your phone number for the booking?"

5. **Email & OTP**:
   - Ask for the user's **email address** to send a verification code.
   - **VERIFICATION STEP**: When the user provides the email, speaks the email address naturally to them (e.g. "is that john at gmail dot com?"). DO NOT spell it out character-by-character.
   - Ask "Is that correct?" and wait for their confirmation.
   - **If they confirm (yes)**: Call `send_otp` with the email.
   - **If they correct you**: Ask for the email again.
   - Ask the user for the code ("I've sent a code to your email...").
   - **Call `verify_otp`** with the code they provide.
   - **CRITICAL**: Do NOT proceed to confirmation until `verify_otp` returns success.

6. **Confirmation**: After ALL info collected AND OTP verified, confirm:
   - **Before confirming, make your THIRD and FINAL related service suggestion (if needed and appropriate)**
   - "Okay, so just to make sure I have this right... I'm booking [Service] on [date] at [time]... and I have your number as [phone]."
   - Brief pause, then: "Should I go ahead and confirm that for you?"

7. **EXECUTION**: When the user provides verbal confirmation (e.g. "yes", "go ahead"), you MUST call the `create_booking` tool immediately with the details collected. Do not ask more questions. JUST CALL THE TOOL.
8. **Handling Rejection**: If they say "no" to confirmation, ask what they would like to change.

### CRITICAL RULES:
- **AUTO-CHECK: Whenever a date is mentioned, IMMEDIATELY call get_availability before proceeding**
- **OTP REQUIRED**: You MUST verify the user's email with an OTP before creating a booking.
- Extract ALL information provided upfront - don't re-ask for what they already told you
- Suggested slots are just EXAMPLES - accept ANY valid time within available periods
- Ask ONE question at a time for missing information only
- Do NOT ask for the user's name (use defaults)
- YOU MUST ask for the phone number if not provided
- If multiple bookings match the phone number, ask identifying questions conversationally
- **UPSELLING LIMIT: Maximum 2-3 related service suggestions per conversation - then STOP**

### Natural Response Patterns:

**Starting responses**: "Okay...", "Alright...", "Sure...", "Got it..."

**Checking information**: "Let me see...", "One moment...", "Let me pull that up..."

**Confirming**: "Perfect...", "Great...", "Sounds good..."

**Transitions**: "And...", "So...", "Now..."

**Upselling naturally**: "By the way...", "Oh, and...", "Just a thought...", "A lot of people also..."

**Example - Instead of robotic**: "What service would you like? Available services are: haircut, facial, massage."

**Say naturally**: "So... what service are you looking for today? We've got haircuts, facials, and massages available."

---

**Remember: You're a friendly salon receptionist having a natural conversation. Use pauses, think out loud briefly, keep it conversational, and gently suggest related services (max 2-3 times) to enhance their experience.**
"""
        super().__init__(instructions=instructions)

    @function_tool
    async def send_otp(
        self,
        context: RunContext,
        email: Annotated[str, "User email address"],
    ):
        from otp_service import generate_otp, hash_otp, send_otp_email, OTP_EXPIRY_MINUTES

        otp = generate_otp()
        
        # Access FSM context attached to session
        fsm_ctx = context.session.fsm.ctx

        fsm_ctx.email = email
        fsm_ctx.otp_hash = hash_otp(otp)
        fsm_ctx.otp_expiry = datetime.now(ZoneInfo("UTC")) + timedelta(minutes=OTP_EXPIRY_MINUTES)
        fsm_ctx.otp_last_sent_at = datetime.now(ZoneInfo("UTC"))
        fsm_ctx.otp_resend_count = 0   # reset on fresh OTP

        send_otp_email(email, otp)

        return (
            "Alright… I’ve sent a six-digit verification code to your email. "
            "It’s valid for five minutes."
        )

    @function_tool
    async def resend_otp(
        self,
        context: RunContext,
    ):
        from otp_service import generate_otp, hash_otp, send_otp_email, OTP_EXPIRY_MINUTES, OTP_RESEND_COOLDOWN_SECONDS, OTP_MAX_RESENDS
        
        # Access FSM context attached to session
        fsm_ctx = context.session.fsm.ctx
        now = datetime.now(ZoneInfo("UTC"))

        # ❌ Too many resends
        if fsm_ctx.otp_resend_count >= OTP_MAX_RESENDS:
            return (
                "I’ve already sent the code a few times. "
                "For security reasons, please try again after some time."
            )

        # ⏳ Cooldown check
        if fsm_ctx.otp_last_sent_at:
            elapsed = (now - fsm_ctx.otp_last_sent_at).total_seconds()
            if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
                wait = int(OTP_RESEND_COOLDOWN_SECONDS - elapsed)
                return f"Please wait {wait} seconds before I resend the code."

        # ✅ Resend allowed
        otp = generate_otp()
        fsm_ctx.otp_hash = hash_otp(otp)
        fsm_ctx.otp_expiry = now + timedelta(minutes=OTP_EXPIRY_MINUTES)
        fsm_ctx.otp_last_sent_at = now
        fsm_ctx.otp_resend_count += 1

        send_otp_email(fsm_ctx.email, otp)

        return (
            "Okay… I’ve sent a new verification code to your email. "
            "Please check and say the six digits slowly."
        )

    @function_tool
    async def verify_otp(
        self,
        context: RunContext,
        otp: Annotated[str, "6 digit code spoken by user"],
    ):
        from otp_service import hash_otp
        # Access FSM context attached to session
        fsm_ctx = context.session.fsm.ctx

        if datetime.now(ZoneInfo("UTC")) > fsm_ctx.otp_expiry:
            return (
                "That code has expired. "
                "Would you like me to send a new one?"
            )

        if hash_otp(otp) == fsm_ctx.otp_hash:
            fsm_ctx.otp_verified = True
            return (
                "Perfect. You’re verified now. "
                "Let me confirm the booking details with you..."
            )

        return (
            "Hmm… that doesn’t seem right. "
            "Please say the six-digit code again, slowly."
        )



    @function_tool
    async def list_available_services(
        self,
        context: RunContext,
    ):
        """List all available services from Cal.com."""
        try:
            await fetch_event_types(force_refresh=True)
            services = get_all_services()
            
            if not services:
                return "I couldn't fetch the available services right now."
            
            service_list = []
            for service in services:
                service_list.append(f"{service['title']} ({service['duration']} min)")
            
            return f"Available services: {', '.join(service_list)}"
        except Exception as e:
            logger.error(f"Error listing services: {e}")
            return "I couldn't fetch the service list right now."

    @function_tool
    async def create_booking(
        self,
        context: RunContext,
        date: Annotated[str, "Date"],
        time: Annotated[str, "Time"],
        guest_phone: Annotated[str, "Phone Number"],
        service: Annotated[str, "Service title exactly as user mentioned"],
    ):
        """Create a new booking for the specified service."""
        try:
            # Find the service
            service_info = find_service_by_name(service)
            
            if not service_info:
                services = get_all_services()
                available = ", ".join([s['title'] for s in services])
                return f"I couldn't find a service matching '{service}'. Available services: {available}"

            # Handle vague time periods by asking for clarification
            if time.lower().strip() in ["morning", "afternoon", "evening", "evening"]:
                 return f"At what time in the {time} would you like to book?"

            current_start_str = parse_datetime(date, time)
            
            # Validate booking time
            try:
                dt_utc = datetime.fromisoformat(current_start_str.replace("Z", "+00:00"))
                dt_local = dt_utc.astimezone(ZoneInfo("Asia/Kolkata"))
                now_local = datetime.now(ZoneInfo("Asia/Kolkata"))
                if dt_local.date() < now_local.date():
                    return "I can't book in the past. Please pick a future date within one week."
                if dt_local > (now_local + timedelta(days=7)):
                    return "I can only book appointments up to 1 week from today. Please pick an earlier date."
            except Exception:
                return "I couldn't understand that date — please provide a valid day within one week."
            
            # Create the booking
            payload = {
                "start": current_start_str,
                "eventTypeSlug": service_info["slug"],
                "username": CAL_USERNAME,
                "attendee": {
                    "name": "Guest",
                    "email": context.session.fsm.ctx.email or "guest@voice.ai",
                    "phoneNumber": normalize_phone(guest_phone),
                    "timeZone": "Asia/Kolkata",
                },
                "metadata": {"title": service_info["title"]},
            }
            
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    f"{CAL_COM_API_URL}/bookings",
                    headers={
                        "Authorization": f"Bearer {CAL_COM_API_KEY}",
                        "Content-Type": "application/json",
                        "cal-api-version": "2024-08-13",
                    },
                    json=payload,
                    timeout=15.0,
                )
                
                if res.status_code in (200, 201):
                    # Send confirmation email
                    from otp_service import send_booking_confirmation_email
                    user_email = context.session.fsm.ctx.email or "guest@voice.ai"
                    send_booking_confirmation_email(user_email, service_info['title'], date, time)
                    
                    return f"Your {service_info['title']} appointment has been confirmed for {date} at {time}. I have sent the email for the confirmed booking."
                else:
                    logger.error(f"Booking failed: {res.status_code} - {res.text}")
                    return f"I couldn't book the {service_info['title']} appointment. Please try a different time slot."

        except Exception as e:
            logger.error(f"Booking error: {e}")
            return "Booking failed. Please try again."

    @function_tool
    async def get_availability(
        self,
        context: RunContext,
        date: Annotated[str, "Date (YYYY-MM-DD or tomorrow)"],
        service: Annotated[str, "Service title"],
        period: Annotated[str, "Optional: morning|afternoon|evening"] = "",
    ):
        """Check availability for a specific service on a given date."""
        try:
            # Find the service
            service_info = find_service_by_name(service)
            
            if not service_info:
                services = get_all_services()
                available = ", ".join([s['title'] for s in services])
                return f"I couldn't find '{service}'. Available services: {available}"
            
            iso = parse_datetime(date, "12:00 PM")
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            now_local = datetime.now(ZoneInfo("Asia/Kolkata"))
            note_prefix = ""
            
            if dt.date() < now_local.date():
                tomorrow = now_local + timedelta(days=1)
                dt = tomorrow
                note_prefix = f"(Showing availability for tomorrow: {dt.strftime('%Y-%m-%d')})\n"

            if dt > (now_local + timedelta(days=7)):
                return "I can only book appointments up to 1 week from today. Please choose a date within one week."

            formatted_date = dt.strftime("%Y-%m-%d")

            # Get availability using V1 slots endpoint (still works with V2 auth)
            params = {
                "apiKey": CAL_COM_API_KEY,
                "eventTypeId": service_info["id"],
                "startTime": f"{formatted_date}T00:00:00.000Z",
                "endTime": f"{formatted_date}T23:59:59.999Z",
            }
            
            async with httpx.AsyncClient() as client:
                res = await client.get(
                    "https://api.cal.com/v1/slots",
                    params=params,
                    timeout=10.0,
                )

            if res.status_code != 200:
                logger.error(f"Availability check failed: {res.status_code} {res.text}")
                return "What time would you like to schedule?"

            json_data = res.json()
            slots_data = json_data.get("slots", json_data)
            
            day_slots = []
            if isinstance(slots_data, dict):
                day_slots = slots_data.get(formatted_date, [])
            elif isinstance(slots_data, list):
                day_slots = slots_data

            if not day_slots:
                return note_prefix + f"No slots available on {formatted_date}. Try another day."

            slots_local = []
            for s in day_slots:
                ts_str = s.get("time")
                if not ts_str:
                    continue
                dt_slot = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                slots_local.append(dt_slot.astimezone(ZoneInfo("Asia/Kolkata")))

            if not slots_local:
                return note_prefix + f"No slots available on {formatted_date}. Try another day."

            def in_period(d: datetime, p: str) -> bool:
                h = d.hour
                if p == "morning":
                    return 6 <= h < 12
                if p == "afternoon":
                    return 12 <= h < 17
                if p == "evening":
                    return 17 <= h < 22
                return False

            period_clean = (period or "").strip().lower()
            if not period_clean:
                available_periods = []
                for p in ("morning", "afternoon", "evening"):
                    if any(in_period(s, p) for s in slots_local):
                        available_periods.append(p)

                if not available_periods:
                    return note_prefix + f"I have slots on {formatted_date}, but none fall into morning/afternoon/evening categories."

                pretty = ", ".join(available_periods)
                return note_prefix + f"I have availability in the following parts of the day: {pretty}. Which part do you prefer?"

            if period_clean not in ("morning", "afternoon", "evening"):
                return "Please choose one of: morning, afternoon, or evening."

            matched = [s for s in slots_local if in_period(s, period_clean)]
            if not matched:
                return note_prefix + f"No {period_clean} slots available on {formatted_date}. Try another part of the day."

            matches_times = [s.strftime("%I:%M %p") for s in matched]
            
            # We return ALL slots to the LLM so it knows everything that is valid.
            # But we add an instruction to only speak a few.
            return (
                f"{note_prefix}Here are all the available {period_clean} slots: {', '.join(matches_times)}. "
                "(SYSTEM NOTE: Only verbally list the first 3 options to the user. "
                "However, accept ANY time from the full list above if the user requests it.)"
            )

        except Exception as e:
            logger.error(f"Error checking availability: {e}")
            return "What time would you like to schedule?"

    @function_tool
    async def check_available_days(
        self,
        context: RunContext,
        service: Annotated[str, "Service title"],
    ):
        """
        Finds the nearest upcoming days that have availability. 
        Use this when the user asks "When are you available?" or "Which days do you have connected?" without specifying a date.
        """
        try:
            # Find the service
            service_info = find_service_by_name(service)
            if not service_info:
                services = get_all_services()
                available = ", ".join([s['title'] for s in services])
                return f"I couldn't find '{service}'. Available services: {available}"

            now_local = datetime.now(ZoneInfo("Asia/Kolkata"))
            start_date_utc = now_local.astimezone(ZoneInfo("UTC"))
            end_date_utc = start_date_utc + timedelta(days=7) # Look ahead 7 days (limit)

            params = {
                "apiKey": CAL_COM_API_KEY,
                "eventTypeId": service_info["id"],
                "startTime": start_date_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "endTime": end_date_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
            
            async with httpx.AsyncClient() as client:
                res = await client.get(
                    "https://api.cal.com/v1/slots",
                    params=params,
                    timeout=10.0,
                )

            if res.status_code != 200:
                logger.error(f"Days check failed: {res.status_code} {res.text}")
                return "I couldn't check my calendar right now. Please try proposing a specific date."

            json_data = res.json()
            slots_data = json_data.get("slots", json_data)
            
            available_days = []
            
            # slots_data is typically { "2023-12-22": [...], "2023-12-23": [...] }
            if isinstance(slots_data, dict):
                sorted_dates = sorted(slots_data.keys())
                for date_str in sorted_dates:
                    day_slots = slots_data[date_str]
                    if day_slots and len(day_slots) > 0:
                        # Check if at least one slot is in the future (if today)
                        # Simplified: just assume if API returns it, it's valid, 
                        # but we should filter past slots if it's strictly today.
                        # For day-level availability, presence of slots is usually enough.
                        try:
                             d = datetime.strptime(date_str, "%Y-%m-%d").date()
                             if d >= now_local.date():
                                 available_days.append(d)
                        except ValueError:
                             continue
                             
            elif isinstance(slots_data, list):
                # Rare case where V1 returns list for single day, unlikely for range query
                pass

            if not available_days:
                return "I don't have any openings in the next 7 days."

            if not available_days:
                return "I don't have any openings in the next 7 days."

            # Return all days to context but instruct to speak only 3
            readable_days = [d.strftime("%A, %B %d") for d in available_days]
            
            return (
                f"I found availability on these days: {', '.join(readable_days)}. "
                "(SYSTEM NOTE: Verbally list only the first 3 days to the user, e.g. 'I have availability on Mon, Tue, and Wed'. "
                "But if the user asks for a later date that is in this list, say yes and proceed.)"
            )

        except Exception as e:
            logger.error(f"Error checking available days: {e}")
            return "I couldn't check availability exactly. Please tell me a specific date you'd like."
        
    @function_tool
    async def reschedule_booking(
        self,
        context: RunContext,
        booking_uid: Annotated[str, "Existing booking UID"],
        new_date: Annotated[str, "New date"],
        new_time: Annotated[str, "New time (must be from availability)"],
        guest_phone: Annotated[str, "Phone number"],
        service: Annotated[str, "Service title for the rescheduled booking"],
    ):
        """Reschedule an existing booking to a new date and time."""
        try:
            # Cancel existing booking
            async with httpx.AsyncClient() as client:
                cancel_res = await client.post(
                    f"{CAL_COM_API_URL}/bookings/{booking_uid}/cancel",
                    headers={
                        "Authorization": f"Bearer {CAL_COM_API_KEY}",
                        "cal-api-version": "2024-08-13",
                    },
                    json={"cancellationReason": "User requested reschedule"},
                    timeout=10.0,
                )

            if cancel_res.status_code not in (200, 201):
                return "I couldn't cancel your existing booking."

            # Find the service
            service_info = find_service_by_name(service)
            if not service_info:
                services = get_all_services()
                available = ", ".join([s['title'] for s in services])
                return f"I couldn't find '{service}'. Available services: {available}"

            # Create new booking
            start_time = parse_datetime(new_date, new_time)

            payload = {
                "start": start_time,
                "eventTypeSlug": service_info["slug"],
                "username": CAL_USERNAME,
                "attendee": {
                    "name": "Guest",
                    "email": "guest@voice.ai",
                    "phoneNumber": normalize_phone(guest_phone),
                    "timeZone": "Asia/Kolkata",
                },
                "metadata": {
                    "title": service_info["title"],
                    "source": "rescheduled-via-voice-agent",
                },
            }

            async with httpx.AsyncClient() as client:
                book_res = await client.post(
                    f"{CAL_COM_API_URL}/bookings",
                    headers={
                        "Authorization": f"Bearer {CAL_COM_API_KEY}",
                        "Content-Type": "application/json",
                        "cal-api-version": "2024-08-13",
                    },
                    json=payload,
                    timeout=15.0,
                )

            if book_res.status_code in (200, 201):
                return f"Your {service_info['title']} appointment has been successfully rescheduled to {new_date} at {new_time}."

            return "I cancelled your old booking, but couldn't create the new one. Please book again."

        except Exception as e:
            logger.error(f"Reschedule error: {e}")
            return "Something went wrong while rescheduling."

    @function_tool
    async def list_bookings(
        self,
        context: RunContext,
        phone_number: Annotated[str, "Phone number used for booking"],
    ):
        """List all upcoming bookings for a phone number."""
        try:
            target_phone = normalize_phone(phone_number)

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

            if response.status_code != 200:
                return "I couldn't access your bookings."

            bookings = response.json().get("data", [])

            # Filter by phone
            matched = []
            for booking in bookings:
                booking_phone = extract_booking_phone(booking)
                if booking_phone and normalize_phone(booking_phone) == target_phone:
                    matched.append(booking)

            if not matched:
                return "I couldn't find any bookings with this phone number."

            # Format results
            results = []
            for b in matched:
                uid = b["uid"]
                start = b["start"]
                title = b.get("title", "Appointment")
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                dt_local = dt.astimezone(ZoneInfo("Asia/Kolkata"))
                results.append(
                    f"{title} on {dt_local.strftime('%B %d at %I:%M %p')} (ID: {uid})"
                )

            return f"I found {len(results)} booking(s): " + "; ".join(results)

        except Exception as e:
            logger.error(f"List bookings error: {e}")
            return "Something went wrong while checking your bookings."

    @function_tool
    async def cancel_booking(
        self,
        context: RunContext,
        booking_uid: Annotated[str, "The UID of the booking to cancel"],
        cancellation_reason: Annotated[str, "Reason for cancellation"] = "User requested cancellation",
    ):
        """Cancel an existing booking."""
        try:
            logger.info(f"Canceling booking: {booking_uid}")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{CAL_COM_API_URL}/bookings/{booking_uid}/cancel",
                    headers={
                        "Authorization": f"Bearer {CAL_COM_API_KEY}",
                        "cal-api-version": "2024-08-13",
                    },
                    json={
                        "cancellationReason": cancellation_reason,
                    },
                    timeout=10.0,
                )
                
                if response.status_code in [200, 201]:
                    return "Your appointment has been cancelled successfully."
                else:
                    logger.error(f"Cancel booking failed: {response.text}")
                    return "I couldn't cancel that appointment. It might have already been cancelled."
                    
        except Exception as e:
            logger.error(f"Error canceling booking: {str(e)}")
            return "There was an issue canceling your appointment. Please try again."


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    
    # Fetch event types on startup
    await fetch_event_types()
    logger.info(f"Available services: {[s['title'] for s in get_all_services()]}")

    # Initialize FSM
    fsm_instance = FSM()

    session = AgentSession(
        # stt=inference.STT(model="assemblyai/universal-streaming", language="en"),
        # stt=inference.STT(model="cartesia/ink-whisper",
        #  language="en"
        # ),
        stt=groq.STT(
            model="whisper-large-v3",
            language="en",
        ),
        llm=inference.LLM(model="openai/gpt-4.1-mini"),
        # llm=groq.LLM(model="openai/gpt-oss-20b"),
        tts=inference.TTS(
            model="cartesia/sonic-3", voice="2b035a4d-c001-49a7-8505-f050c4250d97"
        ),
        # tts=resemble.TTS(
        #     voice_uuid="c99f388c",
        # ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )
    
    # Attach FSM to session for access in tools
    session.fsm = fsm_instance

    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    await ctx.connect()
    await session.say("Hello!! Welcome to TSC Salon. How may i help you?", allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(server)