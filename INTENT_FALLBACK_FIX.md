# Intent Fallback Mechanism - CRITICAL FIX

## The Problem
Even after adding all FSM input tools (`intent_book`, `input_service`, etc.), the LLM was **NOT calling them**!

### Evidence from Logs:
```
13:37:06.698 DEBUG  User transcript: "Book appointment"
13:37:18.070 DEBUG  Started silence monitoring for state START (20.0s)
```

**No tool was called!** The state remained at START even though the user clearly said "book appointment".

## Why This Happens
LLMs don't always recognize when to call function tools, especially for:
- **Intent detection** (book vs cancel vs reschedule)
- **Implicit information** (user says "haircut" but doesn't explicitly say "I want a haircut")
- **Casual language** ("book appointment" vs "I would like to book an appointment")

## The Solution: Intent Fallback

We added **two event handlers** that act as a safety net:

### 1. Tool Execution Logging
```python
@session.on("function_tools_executed")
def on_tools_executed(event):
    for tool_call in event.tool_calls:
        logger.info(f"🔧 Tool executed: {tool_call.name}")
```

**Purpose:** See which tools the LLM is actually calling (or not calling)

### 2. Intent Fallback Handler
```python
@session.on("user_transcript")
def on_user_transcript(event):
    text = event.text.lower().strip()
    fsm = session.fsm
    
    # Manually trigger state transitions based on keywords
```

**Purpose:** If LLM doesn't call the tool, we detect keywords and manually call `fsm.update_state()`

## What It Does

### At START State:
- **Detects:** "book", "appointment", "booking", "schedule"
- **Action:** `fsm.update_state(intent="book")` → Transitions to BOOKING_ASK_SERVICE
- **Detects:** "cancel", "reschedule", "change", "update", "manage"
- **Action:** `fsm.update_state(intent="cancel")` → Transitions to MANAGE_ASK_PHONE

### At BOOKING_ASK_SERVICE:
- **Detects:** Service names (haircut, spa, makeup, etc.)
- **Action:** `fsm.update_state(data={"service": "Haircut"})` → Transitions to BOOKING_ASK_DATE

### At BOOKING_ASK_DATE:
- **Detects:** "tomorrow", "today", day names, date patterns (25th, dec 25)
- **Action:** `fsm.update_state(data={"date": "tomorrow"})` → Transitions to BOOKING_ASK_TIME

### At BOOKING_ASK_TIME:
- **Detects:** "morning", "afternoon", "evening", time patterns (4:30, 4 pm)
- **Action:** `fsm.update_state(data={"time": "4:30 PM"})` → Transitions to BOOKING_ASK_PHONE

### At BOOKING_ASK_PHONE:
- **Detects:** 10-digit phone numbers
- **Action:** `fsm.update_state(data={"phone": "9876543210"})` → Transitions to OTP_ASK_EMAIL

## How It Works Together

### Scenario 1: LLM Calls Tools (Ideal)
```
User: "I want to book a haircut"
LLM: Calls intent_book() ✅
LLM: Calls input_service("haircut") ✅
→ State transitions happen via tools
```

### Scenario 2: LLM Doesn't Call Tools (Fallback)
```
User: "Book appointment"
LLM: Doesn't call intent_book() ❌
Fallback: Detects "book" keyword ✅
Fallback: Calls fsm.update_state(intent="book") ✅
→ State transitions happen via fallback
```

### Scenario 3: Hybrid (Most Common)
```
User: "I want a haircut tomorrow at 4pm"
LLM: Calls intent_book() ✅
LLM: Doesn't call input_service() ❌
Fallback: Detects "haircut" ✅
Fallback: Detects "tomorrow" ✅
Fallback: Detects "4pm" ✅
→ State transitions happen via mix of tools + fallback
```

## Expected Logs Now

### Before (Broken):
```
DEBUG  User transcript: "Book appointment"
DEBUG  Started silence monitoring for state START
```

### After (Fixed):
```
DEBUG  📝 User transcript: 'book appointment' | Current state: START
INFO   🔥 Intent fallback: booking detected from transcript
INFO   FSM State: START → BOOKING_ASK_SERVICE
DEBUG  Started silence monitoring for state BOOKING_ASK_SERVICE
```

## Testing

Restart the agent and try:
```
User: "Book appointment"
Expected: State should transition to BOOKING_ASK_SERVICE

User: "Haircut"
Expected: State should transition to BOOKING_ASK_DATE

User: "Tomorrow"
Expected: State should transition to BOOKING_ASK_TIME

User: "4:30 PM"
Expected: State should transition to BOOKING_ASK_PHONE
```

## Why This Is Better Than Relying Only on Tools

1. **More Reliable:** Works even when LLM fails to call tools
2. **Faster:** Direct keyword matching is instant
3. **Handles Casual Speech:** "book" vs "I would like to book"
4. **Handles Implicit Info:** User says "haircut" without "I want"
5. **Debugging:** Tool execution logs show what LLM is doing

## Important Notes

- Fallback runs **in addition to** tools, not instead of
- If LLM calls a tool, great! If not, fallback catches it
- Fallback uses simple keyword matching (fast and reliable)
- FSM logging shows exactly when state transitions happen
- Tool execution logging shows which tools LLM is calling

## Files Modified
- `/src/agent.py` - Added 2 event handlers with 82 lines of fallback logic
