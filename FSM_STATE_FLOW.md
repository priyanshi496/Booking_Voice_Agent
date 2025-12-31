# FSM State Flow Diagram

## Booking Flow
```
START
  |
  | [User: "I want to book"]
  | Tool: intent_book()
  v
BOOKING_ASK_SERVICE
  |
  | [User: "haircut"]
  | Tool: input_service("haircut")
  v
BOOKING_ASK_DATE
  |
  | [User: "tomorrow"]
  | Tool: input_date("tomorrow")
  v
BOOKING_ASK_TIME
  |
  | [User: "4:30 PM"]
  | Tool: input_time("4:30 PM")
  v
BOOKING_ASK_PHONE
  |
  | [User: "9876543210"]
  | Tool: input_phone("9876543210")
  v
OTP_ASK_EMAIL
  |
  | [User: "user@example.com" + confirms]
  | Tool: send_otp("user@example.com")
  v
OTP_VERIFY
  |
  | [User: "123456"]
  | Tool: verify_otp("123456")
  v
BOOKING_CONFIRM
  |
  | [User: "yes"]
  | Tool: confirm_action() + create_booking()
  v
START (reset)
```

## Manage/Cancel Flow
```
START
  |
  | [User: "I want to cancel"]
  | Tool: intent_manage()
  v
MANAGE_ASK_PHONE
  |
  | [User: "9876543210"]
  | Tool: input_phone("9876543210")
  |   → Fetches bookings from API
  |
  ├─ If 1 booking found ─────────┐
  │                              v
  ├─ If multiple bookings ─> MANAGE_SELECT_BOOKING
  │                              |
  │                              | Tool: select_booking(uid)
  │                              v
  └──────────────────────────> CANCEL_CONFIRM
                                 |
                                 | [User: "yes"]
                                 | Tool: confirm_action() + cancel_booking()
                                 v
                               START (reset)
```

## Key Points

### Before the Fix
- ❌ No input tools existed
- ❌ LLM couldn't call update_state()
- ❌ Agent stuck in START forever
- ❌ Silence prompts always for START state
- ❌ Booking flow never progressed

### After the Fix
- ✅ All 8 input tools added
- ✅ LLM can call update_state() via tools
- ✅ Agent transitions through states correctly
- ✅ Silence prompts match current state
- ✅ Booking flow works end-to-end

### Tools Added
1. `intent_book()` - Start booking flow
2. `intent_manage()` - Start manage flow
3. `input_service(service)` - Capture service
4. `input_date(date)` - Capture date
5. `input_time(time)` - Capture time ← **THIS WAS THE MISSING PIECE IN YOUR LOGS**
6. `input_phone(phone)` - Capture phone
7. `select_booking(uid)` - Select from multiple bookings
8. `confirm_action()` - Confirm final action

### OTP Tools Updated
- `send_otp(email)` - Now calls update_state()
- `verify_otp(code)` - Now calls update_state()
