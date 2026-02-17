
import sys
import os
sys.path.append(os.path.join(os.getcwd(), "src"))

print("Checking imports...")

try:
    import livekit.agents
    print(f"livekit.agents version: {getattr(livekit.agents, '__version__', 'unknown')}")
except ImportError as e:
    print(f"Failed to import livekit.agents: {e}")

try:
    from livekit.agents import (
        Agent, AgentServer, AgentSession, JobContext, JobProcess, RunContext,
        cli, function_tool, inference, room_io,
        AgentStateChangedEvent, UserStateChangedEvent, FunctionToolsExecutedEvent
    )
    print("livekit.agents specific imports: OK")
except ImportError as e:
    print(f"livekit.agents specific imports: FAILED - {e}")

try:
    from livekit.plugins import noise_cancellation, silero, openai, groq, resemble
    print("livekit.plugins imports: OK")
except ImportError as e:
    print(f"livekit.plugins imports: FAILED - {e}")

try:
    from livekit.plugins.turn_detector.multilingual import MultilingualModel
    print("turn_detector import: OK")
except ImportError as e:
    print(f"turn_detector import: FAILED - {e}")

try:
    import otp_service
    print("otp_service import: OK")
except ImportError as e:
    print(f"otp_service import: FAILED - {e}")

print("Done.")
