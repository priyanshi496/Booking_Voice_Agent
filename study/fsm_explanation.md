# 🧭 Deep Dive: `src/fsm.py` (Finite State Machine)

This file is the **Compass** of the application. It tells the agent *exactly* where it is in the conversation and what it should do next. Without this, the agent would be lost and might ask for a phone number before knowing what service you want.

## 1. Imports and Basic Setup
```python
1: from enum import Enum, auto
2: from typing import Optional, Dict, Any
```
-   **Line 1**: We import `Enum` and `auto` to create a strict list of allowed "States". This prevents typos (e.g., trying to set state to "book_confirm" instead of `BOOKING_CONFIRM`).
-   **Line 2**: Standard Python typing to make the code cleaner and less bug-prone.

---

## 2. Defining the States (`State` Class)
Think of these as "Steps" in a flowchart. The agent can only be in **one** step at a time.

```python
4: class State(Enum):
5:     START = auto()
```
-   **START**: The entry point. The agent says "Hello" and waits for the user to say something ("I want a haircut" or "Cancel my meeting").

**Booking Flow Steps:**
```python
15:     BOOKING_ASK_SERVICE = auto()
16:     BOOKING_ASK_DATE = auto()
17:     BOOKING_ASK_TIME = auto()
18:     BOOKING_ASK_PHONE = auto()
19:     BOOKING_CONFIRM = auto()
```
-   These enforce the order: Service -> Date -> Time -> Phone -> Confirm. You cannot skip to Confirm without the others.

**OTP (One Time Password) Steps:**
```python
9:     OTP_ASK_EMAIL = auto()
10:     OTP_SENT = auto()
11:     OTP_VERIFY = auto()
12:     OTP_VERIFIED = auto()
```
-   This handles the security check. We ask for email, send code, and verify it before confirming the booking.

*(Other states for Manage/Cancel/Reschedule follow the same pattern)*

---

## 3. The Memory (`ConversationContext`)
The FSM holds the "State" (where we are), but the Context holds the "Data" (what we know).

```python
35: class ConversationContext:
36:     def __init__(self):
37:         self.service: Optional[str] = None
38:         self.date: Optional[str] = None
39:         self.time: Optional[str] = None
40:         self.phone: Optional[str] = None
```
-   These variables start as `None`. As the user speaks, we fill them.
-   **Example**: User says "Haircut", so `self.service` becomes `"Haircut"`.

```python
45:         self.otp_hash: Optional[str] = None
46:         self.otp_expiry: Optional[datetime] = None
47:         self.otp_verified: bool = False
```
-   These store the secret OTP details. `otp_verified` is the "Golden Ticket". If this is False, no booking happens.

---

## 4. The Logic Engine (`FSM` Class)

### Initialization
```python
52: class FSM:
53:     def __init__(self):
54:         self.state = State.START
55:         self.ctx = ConversationContext()
```
-   When a call starts, we begin at `START` with an empty memory (`ctx`).

---

### Critical Function: `get_system_prompt()`
**This is the most important function in the file.** It tells the LLM how to behave *right now*.

```python
63: base = f"You are Zara... today is {now...}"
```
-   Defines the persona "Zara". Every prompt starts with this.

**Handling `START` State:**
```python
65:         if self.state == State.START:
66:             return base + " Greet the user. If they want to book... call `intent_book`..."
```
-   If we just started, the instruction is simplistic: "Just say hi and deduce intent."

**Handling `BOOKING_ASK_SERVICE`:**
```python
69:         if self.state == State.BOOKING_ASK_SERVICE:
70:             return base + " Ask the user 'What service would you like to book?'..."
```
-   **Hypnotic Instruction**: The LLM is commanded to ask *only* for the service. This stops it from hallucinating or asking for the phone number too early.

**Handling `BOOKING_ASK_DATE` (Context Injection):**
```python
72:         if self.state == State.BOOKING_ASK_DATE:
73:             msg = base + f" Service: {self.ctx.service}. Ask 'What day works for you?'..."
```
-   **Notice `{self.ctx.service}`**: We inject the data we already collected ("Haircut") into the prompt.
-   **Result Prompt**: "You are Zara. The user wants a **Haircut**. Ask them for the date."
-   The LLM feels smart because it remembers "Haircut", but actually, we just reminded it.

---

### Critical Function: `update_state()`
This function actually moves the player piece on the board.

```python
151:         if self.state == State.START and intent:
152:             if intent == "book":
153:                 self.state = State.BOOKING_ASK_SERVICE
```
-   If we are at Start and user says "I want to book" (`intent="book"`), we move to `BOOKING_ASK_SERVICE`.

**The Booking Waterfall:**
```python
160:         elif self.state == State.BOOKING_ASK_SERVICE and "service" in data:
161:             self.ctx.service = data["service"]
162:             self.state = State.BOOKING_ASK_DATE
```
-   If we asked for a service, and the tool gave us a service (`data["service"]`), we save it to context and move to `BOOKING_ASK_DATE`.

**Skip Logic (Optimization):**
```python
164:             if "date" in data:
165:                  self.ctx.date = data["date"]
166:                  self.state = State.BOOKING_ASK_TIME
```
-   If the user said "I want a haircut **tomorrow**", we got both Service AND Date.
-   This code sees the date is present and **skips** the `ASK_DATE` step, moving straight to `ASK_TIME`. This makes the bot feel natural and efficient.

**OTP Transition:**
```python
194:         elif self.state == State.OTP_VERIFY and intent == "otp_success":
195:             self.state = State.BOOKING_CONFIRM
```
-   The only way to reach `BOOKING_CONFIRM` is if `otp_success` happens. This creates a secure gate.

---

## Summary
1.  **Definitions**: We define valid steps (`State` enum).
2.  **Memory**: We define a container for data (`ConversationContext`).
3.  **Prompting**: We dynamically change the LLM's instructions based on the step (`get_system_prompt`).
4.  **Transitions**: We move between steps based on data collected (`update_state`).

This file ensures the agent is **Reliable, Structured, and Cannot be tricked** into skipping steps.
