# 📅 Deep Dive: `src/booking.py` (The Hands)
> **⚠️ CRITICAL EXAM NOTE:**  
> This file is **NOT CURRENTLY USED** by the main application (`agent.py`).  
> The logic inside this file (API calls, time parsing) has been **copied directly into `agent.py`**.  
>  
> - **Is it necessary?** No, the code in `agent.py` runs fine without it.  
> - **Why is it here?** It likely represents a "cleaner" version of the code that the developers *intended* to use but haven't switched to yet.  
>  
> *The explanation below describes what the code DOES, but remember it is effectively "Dead Code" right now.*

    

This file handles the "dirty work" of talking to the outside world (Cal.com API). The Agent asks for a booking, but this file actually *makes* it happen.

## 1. Setup & Config
```python
15: CAL_COM_API_KEY = os.getenv("CAL_COM_API_KEY")
20: EVENT_TYPE_SLUG = "30min"
```
-   We need an API Key to talk to Cal.com.
-   **Slug**: A "slug" is the URL-friendly name of the event type (e.g., `cal.com/user/30min`). We default to "30min".

---

## 2. The Heavy Lifter: `parse_datetime()`
Time is hard. Users say "tomorrow", "next Friday", "5pm". Computers need `2024-01-02T17:00:00Z`.

```python
43: def parse_datetime(date_str, time_str, timezone="Asia/Kolkata"):
```

**Step 1: Clean Dates**
```python
62:         if "tomorrow" in date_clean.lower():
63:             target_date = now_in_tz + timedelta(days=1)
```
-   We manually handle "tomorrow" because standard libraries sometimes struggle with relative days without context.

**Step 2: Fallback to `dateutil`**
```python
70:                  parsed = parser.parse(date_clean, default=now_in_tz, fuzzy=True)
```
-   If it's not "tomorrow", we let the powerful `dateutil` library figure it out. It knows that "Dec 25" means "December 25th".

**Step 3: Handle Times (The Tricky Part)**
```python
83:     try:
84:         # Use a dummy date to parse time efficiently
85:         time_parsed = parser.parse(time_input, default=now_in_tz)
```
-   This converts "5 p.m." or "17:00" into a Time object.

**Step 4: Combine & Convert to UTC**
```python
99:     final_dt_aware = datetime.combine(target_date.date(), target_time, tzinfo=current_tz)
105:    return final_dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
```
-   **Crucial**: APIs almost always want **UTC** time. We take the local Indian time and convert it to Universal Time (UTC) before sending.

---

## 3. The Booking Service Class

### A. `create_booking`
```python
167:     async def create_booking(self, date, time, guest_phone, title):
```
-   **Step 1**: Parse the date/time (Line 169).
-   **Step 2**: Create the Payload (the JSON data Cal.com expects).
    ```python
    180:             payload = {
    181:                 "eventTypeId": event_type_id,
    182:                 "start": start_time,
    ...
    186:                     "location": {"value": "phone", "optionValue": phone},
    ```
-   **Step 3**: Send POST request (Line 201).
-   **Step 4**: Return Success/Fail.
    -   If success (`201`), we return "Your meeting is confirmed. Ref ID: ...".

### B. `get_availability` (The logic behind the "When are you free?" question)
```python
224:     async def get_availability(self, date_str):
```
-   **Step 1**: Calculate Start/End of the day (00:00 to 23:59).
-   **Step 2**: Call Cal.com API `v1/slots`.
    ```python
    232:                     f"https://api.cal.com/v1/availability"
    ```
-   **Step 3**: Filter Empty Days.
-   **Step 4**: Convert UTC slots back to IST (Indian Standard Time).
    ```python
    279:                 times.append(dt.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%I:%M %p"))
    ```
-   **Result**: Returns a simple list like `["10:00 AM", "10:30 AM"]`.

### C. `list_bookings`
```python
287:     async def list_bookings(self, phone_number):
```
-   **Purpose**: Used for "Cancel my appointment".
-   **Logic**:
    1.  Downloads *all* upcoming bookings.
    2.  **Line 313**: Loops through them and checks `if normalize_phone(booking_phone) == target_phone`.
    3.  We only show the user *their* bookings (filtered by phone number).

### D. `reschedule_booking`
```python
361:     async def reschedule_booking(self, booking_uid, new_date, new_time...):
```
-   **Smart Logic**:
    1.  **First, try to CREATE the new booking.** (Line 365)
    2.  Only if that works, **CANCEL the old one.** (Line 370)
-   **Why?**: If we cancel first, and then the new date is full, the user loses their original spot! This is a "Safety First" approach.

---

## Summary
-   **`booking.py`** isolates the external API logic.
-   It handles **Timezones** (the hardest part of calendars).
-   It provides "Transaction-like" safety for rescheduling (Book NEW -> Cancel OLD).
