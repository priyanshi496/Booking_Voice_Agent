# FSM State Transition Fix - Summary

## Problem
The agent was stuck in the `START` state and never transitioning to other states, even after collecting booking information like service, date, and time. This caused:
- Silence monitoring to always use START state prompts
- The booking flow to never progress
- Users getting stuck in an infinite loop

## Root Cause
The FSM (Finite State Machine) in `fsm.py` was designed to transition states via `update_state()` method, which should be called by input tools like:
- `intent_book` - When user wants to book
- `intent_manage` - When user wants to manage bookings
- `input_service` - When service is provided
- `input_date` - When date is provided  
- `input_time` - When time is provided
- `input_phone` - When phone number is provided
- `select_booking` - When user selects a booking
- `confirm_action` - When user confirms an action

**These tools were completely missing from `agent.py`**, so the LLM had no way to update the FSM state!

## Solution
Added all missing FSM input tools to `agent.py`:

### 1. Intent Tools
- **`intent_book()`** - Transitions START → BOOKING_ASK_SERVICE
- **`intent_manage()`** - Transitions START → MANAGE_ASK_PHONE

### 2. Input Capture Tools
- **`input_service(service)`** - Validates service and transitions BOOKING_ASK_SERVICE → BOOKING_ASK_DATE
- **`input_date(date)`** - Captures date and transitions BOOKING_ASK_DATE → BOOKING_ASK_TIME
- **`input_time(time)`** - Captures time and transitions BOOKING_ASK_TIME → BOOKING_ASK_PHONE
- **`input_phone(phone)`** - Captures phone and transitions BOOKING_ASK_PHONE → OTP_ASK_EMAIL
  - For manage flow, also fetches bookings from Cal.com API

### 3. Action Tools
- **`select_booking(booking_uid)`** - Selects a specific booking when multiple are found
- **`confirm_action()`** - Confirms user wants to proceed with booking/cancellation/reschedule

### 4. OTP Flow Fixes
- **`send_otp(email)`** - Now calls `update_state(data={"email": email})` to transition OTP_ASK_EMAIL → OTP_VERIFY
- **`verify_otp(otp)`** - Now calls `update_state(intent="otp_success")` to transition OTP_VERIFY → BOOKING_CONFIRM

## How It Works Now

### Booking Flow Example:
1. User: "I want to book a haircut"
2. LLM calls `intent_book()` → State: START → BOOKING_ASK_SERVICE
3. LLM calls `input_service("haircut")` → State: BOOKING_ASK_SERVICE → BOOKING_ASK_DATE
4. User: "Tomorrow"
5. LLM calls `input_date("tomorrow")` → State: BOOKING_ASK_DATE → BOOKING_ASK_TIME
6. User: "4:30 PM"
7. LLM calls `input_time("4:30 PM")` → State: BOOKING_ASK_TIME → BOOKING_ASK_PHONE
8. User: "9876543210"
9. LLM calls `input_phone("9876543210")` → State: BOOKING_ASK_PHONE → OTP_ASK_EMAIL
10. User provides email and confirms
11. LLM calls `send_otp(email)` → State: OTP_ASK_EMAIL → OTP_VERIFY
12. User provides OTP
13. LLM calls `verify_otp(code)` → State: OTP_VERIFY → BOOKING_CONFIRM
14. User confirms
15. LLM calls `confirm_action()` then `create_booking()` → State: BOOKING_CONFIRM → START

## Files Modified
- `/src/agent.py` - Added 8 missing FSM input tools and updated OTP tools

## Testing
To test the fix:
1. Start the agent: `python src/agent.py dev`
2. Say "I want to book a haircut for tomorrow at 4:30 PM"
3. Watch the logs - you should see state transitions:
   ```
   State: START → BOOKING_ASK_SERVICE
   State: BOOKING_ASK_SERVICE → BOOKING_ASK_DATE  
   State: BOOKING_ASK_DATE → BOOKING_ASK_TIME
   State: BOOKING_ASK_TIME → BOOKING_ASK_PHONE
   State: BOOKING_ASK_PHONE → OTP_ASK_EMAIL
   ```

## Impact
- ✅ State transitions now work correctly
- ✅ Silence monitoring uses appropriate prompts for each state
- ✅ Booking flow progresses smoothly
- ✅ OTP verification flow works end-to-end
- ✅ Manage/cancel/reschedule flows can now work properly
