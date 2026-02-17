# 🤖 Deep Dive: `src/agent.py` (The Brain)

This is the **Main Controller**. It connects the standard components (Speech-to-Text, LLM, Text-to-Speech) and defines the **Tools** the AI uses.

## 1. The Setup (Imports & Config)
```python
26:     cli,
27:     function_tool,
```
-   **`cli`**: Allows us to run this file from the command line (`python agent.py start`).
-   **`function_tool`**: The magic decorator that turns a Python function into something ChatGPT can "see" and "call".

```python
36: from fsm import FSM,State
```
-   We import our "Compass" (FSM) to use inside the agent.

---

## 2. Helper Functions (The Utilities)
These are boring but necessary functions used by the Agent.

```python
56: async def fetch_event_types(force_refresh=False):
```
-   **Purpose**: Go to Cal.com API and download the list of services (Haircut, Spa, etc.).
-   **Why Cache?**: We don't want to call the API every single time the user speaks. We cache it for 5 minutes (`ttl_seconds=300`).

```python
269: class SilenceMonitor:
```
-   **Concurrency Magic**: This runs in the *background*.
-   **Logic**: If the agent is `listening` (waiting for user) and 10 seconds pass with NO audio, this class wakes up and says "Hello? Are you there?".
-   **Why?**: Phone calls have silence. If the user stops talking, the AI should check in, like a real human.

---

## 3. The Main Agent Class (`Assistant`)
This allows us to customize the standard LiveKit Agent.

### A. Initialization (The Persona)
```python
413: class Assistant(Agent):
414:     def __init__(self) -> None:
```
**The Instructions (System Prompt):**
```python
422:         instructions = f"""
423:         You are Zara Patel... warm INDIAN ENGLISH accent...
428:         ### LANGUAGE BEHAVIOR (AUTO-DETECT):
429:         1. **Dynamic Switching**: You must automatically detect the language...
```
-   **Lines 422-661**: This huge block is the **System Prompt**. It tells the LLM:
    -   Who it is (Zara).
    -   How to speak (Indian English, "Hinglish").
    -   **Rules**: "Never ask for language preference", "Always verify OTP".
-   **Upselling Logic (Lines 498-506)**: "Suggest related services MAXIMUM 2-3 times". This business logic is hard-coded here.

---

### B. The Tools (The Hands)
These are methods marked with `@function_tool`. The LLM *reads* the docstring to know when to use them.
 
**1. `send_otp`**
```python
665:     async def send_otp(self, context, email):
```
-   **Trigger**: User gives email.
-   **Action**: Generates a code, saves it to `fsm_ctx` (memory), and sends the email.
-   **Critical**: It updates state: `context.session.fsm.update_state(data={"email": email})`.

**2. `intent_book` / `intent_manage`**
```python
781:     async def intent_book(self, context):
```
-   **Trigger**: User says "I want to book".
-   **Action**: Simply calls `fsm.update_state(intent="book")`.
-   **Effect**: The FSM sees this and says "Okay, next prompt is: ASK_SERVICE". The agent merely *relays* the intent to the FSM.

**3. `input_service` / `input_date` / `input_time`**
```python
799:     async def input_service(self, context, service):
```
-   **Trigger**: User says "Haircut".
-   **Action**:
    1.  Validates if "Haircut" exists in our list.
    2.  Updates FSM: `fsm.update_state(data={"service": "Haircut"})`.
-   **Why a tool?**: We don't want the LLM to just *chat* about haircuts. We want it to *register* the choice formally in the system.

**4. `get_availability` (The Complex One)**
```python
1041:     async def get_availability(self, context, date, service, ...):
```
-   **Trigger**: "Is 5 PM free?" or "When are you free?"
-   **Logic**:
    1.  Calls `booking.py` -> `get_availability`.
    2.  **Smart Filtering**: If user asks "Morning", it filters the list for 6am-12pm.
    3.  **Prompt Engineering in Return Value**:
        ```python
        1141: return "... (SYSTEM NOTE: Only verbally list the first 3 options...)"
        ```
        -   We return a *note to the AI* along with the data. We tell it "Don't read all 50 slots. Just read 3." This keeps the voice response natural.

---

## 4. The Entry Point (`server` setup)
```python
1416: async def my_agent(ctx: JobContext):
```
-   This runs when a user connects.
-   **Step 1**: `await fetch_event_types()` (Pre-load data).
-   **Step 2**: `fsm_instance = FSM()` (Create a fresh brain for this user).
-   **Step 3**: `AgentSession(...)` (Configure the AI models).
    -   `stt=groq.STT(...)`: We use **Whisper** (via Groq) for super-fast listening.
    -   `llm=inference.LLM(...)`: We use **GPT-4** (or similar).
    -   `tts=inference.TTS(...)`: We use **Cartesia** for realistic voice.
-   **Step 4**: `session.start(...)`.
-   **Step 5**: `session.say("Hello!...")`. The conversation begins!

---

## Summary
-   **`agent.py`** is the **Director**.
-   It sets the stage (System Prompt).
-   It provides the props (Tools).
-   It delegates the script-writing (Logic) to `fsm.py` and the heavy lifting (API calls) to `booking.py`.
-   **Key Takeaway**: The `@function_tool` decorators are the bridge between the "Vague AI" and the "Strict Python Code".
