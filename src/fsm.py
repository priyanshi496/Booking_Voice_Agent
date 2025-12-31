from enum import Enum, auto
from typing import Optional, Dict, Any

class State(Enum):
    START = auto()


    # OTP Verification
    OTP_ASK_EMAIL = auto()
    OTP_SENT = auto()
    OTP_VERIFY = auto()
    OTP_VERIFIED = auto()
    
    # Booking Flow
    BOOKING_ASK_SERVICE = auto()
    BOOKING_ASK_DATE = auto()
    BOOKING_ASK_TIME = auto()
    BOOKING_ASK_PHONE = auto()
    BOOKING_CONFIRM = auto()
    
    # Manage/List Flow (common for update/cancel)
    MANAGE_ASK_PHONE = auto()
    MANAGE_LIST_BOOKINGS = auto() # System does this, then transitions
    MANAGE_SELECT_BOOKING = auto()
    
    # Cancel Flow
    CANCEL_CONFIRM = auto()
    
    # Reschedule Flow
    RESCHEDULE_ASK_SERVICE = auto()
    RESCHEDULE_ASK_DATE = auto()
    RESCHEDULE_ASK_TIME = auto()
    RESCHEDULE_CONFIRM = auto()

class ConversationContext:
    def __init__(self):
        self.service: Optional[str] = None
        self.date: Optional[str] = None
        self.time: Optional[str] = None
        self.phone: Optional[str] = None
        self.booking_uid: Optional[str] = None
        self.bookings_list: list = [] # Cache for selection
        self.intent: Optional[str] = None # 'book', 'cancel', 'reschedule'
        self.email: Optional[str] = None
        self.otp_hash: Optional[str] = None
        self.otp_expiry: Optional[datetime] = None
        self.otp_verified: bool = False
        # 🔐 Resend protection
        self.otp_last_sent_at = None
        self.otp_resend_count = 0

class FSM:
    def __init__(self):
        self.state = State.START
        self.ctx = ConversationContext()
    
    def get_system_prompt(self) -> str:
        """
        Returns the instructions for the LLM based on the current state.
        """
        from datetime import datetime
        now = datetime.now()
        base = f"You are Zara, a state-aware calendar assistant for TSC Salon. The usage location is Asia/Kolkata and today is {now.strftime('%A, %d %B %Y')}. Your main goal is to help users manage salon appointments. If the user asks about ANYTHING else, politely decline."
        
        if self.state == State.START:
            return base + " Greet the user. If they want to book, call `intent_book`. If they want to update/cancel, call `intent_manage`. Do not ask for details yet."
            
        # --- BOOKING ---
        if self.state == State.BOOKING_ASK_SERVICE:
            return base + " Ask the user 'What service would you like to book?'. You can call `list_available_services` to see what is offered. If the user specifies a service, call `input_service`."

        if self.state == State.BOOKING_ASK_DATE:
            msg = base + f" Service: {self.ctx.service}. Ask 'What day works for you?'. When user provides a date, call `input_date`. CRITICAL: Whenever a date is mentioned, you should plan to use `get_availability` immediately after."
            return msg
            
        if self.state == State.BOOKING_ASK_TIME:
            date_str = self.ctx.date or "the date"
            return base + f" Service: {self.ctx.service}, Date: {date_str}. Use `get_availability` to check slots if you haven't yet. presenting available slots (morning/afternoon/night). Ask 'What time works?'. When provided, call `input_time`."
            
        if self.state == State.BOOKING_ASK_PHONE:
            return base + " Ask for PHONE NUMBER to finalize the booking. When provided, call `input_phone`."
            
        if self.state == State.BOOKING_CONFIRM:
            return base + f" details: Service={self.ctx.service}, Date={self.ctx.date}, Time={self.ctx.time}, Phone={self.ctx.phone}. Confirm with the user: 'Just to confirm, I'm booking [Service] on [Date] at [Time] for [Phone]. Should I go ahead?'. If yes, call `create_booking` with the gathered details."

        # --- MANAGE (List) ---
        if self.state == State.MANAGE_ASK_PHONE:
            return base + " Ask for PHONE NUMBER to find bookings. Call `input_phone` when provided."
            
        if self.state == State.MANAGE_SELECT_BOOKING:
            return base + " Found multiple bookings. Ask user to select one (e.g. by time). Call `select_booking` with the UID or index."

        # --- CANCEL ---
        if self.state == State.CANCEL_CONFIRM:
            if self.ctx.intent == "cancel_all":
                count = len(self.ctx.bookings_list)
                return base + f" Warn the user they are about to cancel {count} appointments. Ask 'Are you sure you want to cancel ALL appointments?'. Call `cancel_booking` for each appointment if yes."
            return base + " Ask 'Are you sure you want to cancel this appointment?'. Call `cancel_booking` if yes."

        # --- RESCHEDULE ---
        if self.state == State.RESCHEDULE_ASK_SERVICE:
             return base + " To reschedule, we need to create a new booking. Ask 'What service is this for?' (or confirm if it's the same). Call `input_service`."

        if self.state == State.RESCHEDULE_ASK_DATE:
            return base + " Ask for NEW DATE. Call `input_date`. Remember to check availability."
        
        if self.state == State.RESCHEDULE_ASK_TIME:
            return base + f" Ask for NEW TIME on {self.ctx.date}. Use `get_availability`. Call `input_time`."
            
        if self.state == State.RESCHEDULE_CONFIRM:
            return base + f" Confirm reschedule: {self.ctx.service} on {self.ctx.date} at {self.ctx.time}. Call `confirm_action`."

        # OTP Verification
        if self.state == State.OTP_ASK_EMAIL:
            return base + (
                "Ask for the user's email address. "
                "Once provided, SPELL IT OUT character-by-character (e.g. 'a-b-c-@-g-m-a-i-l-.-c-o-m') to verify. "
                "Ask 'Is that correct?'. Only after the user confirms 'yes', call `send_otp`."
            )

        if self.state == State.OTP_SENT:
            return base + (
                "Tell the user that an OTP was sent to their email. "
                "Ask them to say the 6-digit code. "
                "If they ask to resend, call `resend_otp`."
            )

        if self.state == State.OTP_VERIFY:
            return base + (
                "Listen for a 6-digit number. "
                "If correct, confirm verification and continue. "
                "If incorrect or expired, politely ask to retry. "
                "If the user says they didn’t receive the code, or asks to resend, you MUST call the `resend_otp` tool."
            )

        return base + " How can I help?"

    def update_state(self, intent: str = None, data: Dict[str, Any] = None):
        """
        Transitions the state based on logic.
        """
        import logging
        logger = logging.getLogger("fsm")
        
        old_state = self.state
        
        if data is None:
            data = {}
            
        # START intent handling
        if self.state == State.START and intent:
            if intent == "book":
                self.state = State.BOOKING_ASK_SERVICE
                self.ctx.intent = "book"
            elif intent in ["cancel", "update", "reschedule", "cancel_all"]:
                self.ctx.intent = intent
                self.state = State.MANAGE_ASK_PHONE
        
        # BOOKING FLOW
        elif self.state == State.BOOKING_ASK_SERVICE and "service" in data:
            self.ctx.service = data["service"]
            self.state = State.BOOKING_ASK_DATE
            # Optimization: if date/time provided upfront
            if "date" in data:
                 self.ctx.date = data["date"]
                 self.state = State.BOOKING_ASK_TIME
                 if "time" in data:
                     self.ctx.time = data["time"]
                     self.state = State.BOOKING_ASK_PHONE

        elif self.state == State.BOOKING_ASK_DATE and "date" in data:
            self.ctx.date = data["date"]
            self.state = State.BOOKING_ASK_TIME
            if "time" in data:
                 self.ctx.time = data["time"]
                 self.state = State.BOOKING_ASK_PHONE
            
        elif self.state == State.BOOKING_ASK_TIME and "time" in data:
            self.ctx.time = data["time"]
            self.state = State.BOOKING_ASK_PHONE
            if "phone" in data:
                self.ctx.phone = data["phone"]
                self.state = State.BOOKING_CONFIRM
            
        elif self.state == State.BOOKING_ASK_PHONE and "phone" in data:
            self.ctx.phone = data["phone"]
            self.state = State.OTP_ASK_EMAIL
            
        # OTP FLOW
        elif self.state == State.OTP_ASK_EMAIL and "email" in data:
            self.ctx.email = data["email"]
            self.state = State.OTP_VERIFY
            
        elif self.state == State.OTP_VERIFY and intent == "otp_success":
            self.state = State.BOOKING_CONFIRM
            
        elif self.state == State.BOOKING_CONFIRM and intent == "confirm":
            # Action should be taken by agent, then reset
            self.state = State.START 
            
        # MANAGE FLOW
        elif self.state == State.MANAGE_ASK_PHONE:
            # Note: Caller must provide BOTH phone and bookings if success
            if "phone" in data:
                self.ctx.phone = data["phone"]
            
            if "bookings" in data:
                bookings = data["bookings"]
                # Store list for everyone
                self.ctx.bookings_list = bookings
                
                if self.ctx.intent == "cancel_all":
                     # Go straight to confirm, assuming we found bookings
                     if bookings:
                        self.state = State.CANCEL_CONFIRM
                else:
                    if len(bookings) == 1:
                        self.ctx.booking_uid = bookings[0]['uid']
                        self._route_intent_from_manage()
                    elif len(bookings) > 1:
                        self.state = State.MANAGE_SELECT_BOOKING
            else:
                pass
                
        elif self.state == State.MANAGE_SELECT_BOOKING and "booking_uid" in data:
            self.ctx.booking_uid = data["booking_uid"]
            self._route_intent_from_manage()

        # SPECIFIC ACTION FLOWS
        elif self.state == State.CANCEL_CONFIRM and intent == "confirm":
            self.state = State.START
        
        elif self.state == State.RESCHEDULE_ASK_SERVICE and "service" in data:
            self.ctx.service = data["service"]
            self.state = State.RESCHEDULE_ASK_DATE
            
        elif self.state == State.RESCHEDULE_ASK_DATE and "date" in data:
            self.ctx.date = data["date"]
            self.state = State.RESCHEDULE_ASK_TIME
            if "time" in data:
                self.ctx.time = data["time"]
                self.state = State.RESCHEDULE_CONFIRM
            
        elif self.state == State.RESCHEDULE_ASK_TIME and "time" in data:
            self.ctx.time = data["time"]
            self.state = State.RESCHEDULE_CONFIRM
            
        elif self.state == State.RESCHEDULE_CONFIRM and intent == "confirm":
            self.state = State.START
        
        # Log state transition
        if old_state != self.state:
            logger.info(f"FSM State: {old_state.name} → {self.state.name}")
        if data:
            logger.debug(f"FSM Data updated: {data}")
            
    def _route_intent_from_manage(self):
        if self.ctx.intent == "cancel":
            self.state = State.CANCEL_CONFIRM
        elif self.ctx.intent == "reschedule" or self.ctx.intent == "update":
            # We used to ask for date, now we might ask for service first if not known,
            # but usually for reschedule we might assume same service or ask?
            # Agent.py reschedule tool requires 'service'. So we must ask.
            self.state = State.RESCHEDULE_ASK_SERVICE
        else:
            self.state = State.START
