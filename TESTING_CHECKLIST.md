# Testing Checklist for FSM Fix

## Pre-Test Setup
- [ ] Ensure `.env.local` has all required API keys
- [ ] Cal.com API is accessible
- [ ] Email service is configured for OTP

## Test 1: Basic Booking Flow
**Objective:** Verify state transitions work correctly

### Steps:
1. Start agent: `python src/agent.py dev`
2. Say: "I want to book a haircut"
3. **Expected:** Agent should call `intent_book()` and transition to BOOKING_ASK_SERVICE
4. Say: "Haircut"
5. **Expected:** Agent should call `input_service("haircut")` and transition to BOOKING_ASK_DATE
6. Say: "Tomorrow"
7. **Expected:** Agent should call `input_date("tomorrow")` and transition to BOOKING_ASK_TIME
8. Say: "4:30 PM"
9. **Expected:** Agent should call `input_time("4:30 PM")` and transition to BOOKING_ASK_PHONE
10. Say: "9876543210"
11. **Expected:** Agent should call `input_phone("9876543210")` and transition to OTP_ASK_EMAIL

### Check Logs For:
```
DEBUG  agent  State transition: START → BOOKING_ASK_SERVICE
DEBUG  agent  State transition: BOOKING_ASK_SERVICE → BOOKING_ASK_DATE
DEBUG  agent  State transition: BOOKING_ASK_DATE → BOOKING_ASK_TIME
DEBUG  agent  State transition: BOOKING_ASK_TIME → BOOKING_ASK_PHONE
DEBUG  agent  State transition: BOOKING_ASK_PHONE → OTP_ASK_EMAIL
```

## Test 2: Silence Monitoring
**Objective:** Verify silence prompts match current state

### Steps:
1. Start booking flow (follow Test 1 steps 1-5)
2. **Wait 20 seconds without speaking**
3. **Expected:** Agent should say a BOOKING_ASK_TIME specific prompt like:
   - "What time works best for you?"
   - NOT the generic START prompt: "Are you there? I'm still here to help you..."

### Check Logs For:
```
INFO   agent  Silence prompt 1/3 for state BOOKING_ASK_TIME: What time works best...
```

## Test 3: OTP Flow
**Objective:** Verify OTP state transitions

### Steps:
1. Complete booking flow up to phone number
2. Provide email address
3. **Expected:** Agent calls `send_otp()` and transitions to OTP_VERIFY
4. Provide OTP code
5. **Expected:** Agent calls `verify_otp()` and transitions to BOOKING_CONFIRM

### Check Logs For:
```
DEBUG  agent  State transition: OTP_ASK_EMAIL → OTP_VERIFY
DEBUG  agent  State transition: OTP_VERIFY → BOOKING_CONFIRM
```

## Test 4: Complete End-to-End Booking
**Objective:** Verify full booking creation works

### Steps:
1. Complete all steps from Test 1
2. Provide email and OTP
3. Confirm booking when asked
4. **Expected:** 
   - Agent calls `confirm_action()` then `create_booking()`
   - Booking created in Cal.com
   - State resets to START
   - Confirmation email sent

## Test 5: Manage Flow
**Objective:** Verify manage/cancel flow works

### Steps:
1. Say: "I want to cancel my appointment"
2. **Expected:** Agent calls `intent_manage()` and transitions to MANAGE_ASK_PHONE
3. Provide phone number
4. **Expected:** Agent calls `input_phone()` and fetches bookings
5. If multiple bookings, select one
6. **Expected:** Agent transitions to CANCEL_CONFIRM
7. Confirm cancellation
8. **Expected:** Booking cancelled, state resets to START

## Common Issues to Watch For

### Issue: State Still Stuck at START
**Symptoms:** Logs show "Silence prompt for state START" even after providing service/date/time
**Cause:** Tools not being called by LLM
**Fix:** Check LLM prompt includes tool descriptions

### Issue: Tools Called But State Not Changing
**Symptoms:** Logs show tool execution but no state transition
**Cause:** `update_state()` not being called inside tool
**Fix:** Verify each tool has `context.session.fsm.update_state()` call

### Issue: Wrong State Transitions
**Symptoms:** State jumps incorrectly (e.g., START → BOOKING_CONFIRM)
**Cause:** FSM logic in `fsm.py` has bugs
**Fix:** Review `update_state()` method in `fsm.py`

## Success Criteria
- ✅ All state transitions happen correctly
- ✅ Silence prompts match current state
- ✅ OTP flow works end-to-end
- ✅ Booking created successfully
- ✅ State resets to START after completion
- ✅ No errors in logs

## Debugging Tips
1. **Enable verbose logging:**
   ```python
   logging.basicConfig(level=logging.DEBUG)
   ```

2. **Add state logging in FSM:**
   ```python
   def update_state(self, intent=None, data=None):
       old_state = self.state
       # ... existing logic ...
       logger.debug(f"State transition: {old_state} → {self.state}")
   ```

3. **Monitor tool calls:**
   Look for `FunctionToolsExecutedEvent` in logs

4. **Check FSM context:**
   ```python
   logger.debug(f"FSM Context: service={self.ctx.service}, date={self.ctx.date}, time={self.ctx.time}")
   ```
