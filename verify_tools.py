#!/usr/bin/env python3
"""
Quick verification script to check if FSM input tools are properly defined in agent.py
"""

import sys
import inspect

# Import the Assistant class
sys.path.insert(0, '/Users/priyanshimodi/Documents/projects/TSC/TSC-livekit-main/src')
from agent import Assistant

# Get all methods from Assistant class
assistant = Assistant()
methods = [method for method in dir(assistant) if not method.startswith('_')]

# Check for required FSM input tools
required_tools = [
    'intent_book',
    'intent_manage',
    'input_service',
    'input_date',
    'input_time',
    'input_phone',
    'select_booking',
    'confirm_action',
]

print("=" * 60)
print("FSM INPUT TOOLS VERIFICATION")
print("=" * 60)

print("\n✓ Checking for required FSM input tools:\n")

all_found = True
for tool in required_tools:
    if tool in methods:
        # Check if it's a function tool
        method = getattr(assistant, tool)
        if hasattr(method, '__wrapped__'):
            print(f"  ✅ {tool:20s} - Found (function_tool)")
        else:
            print(f"  ⚠️  {tool:20s} - Found but not decorated with @function_tool")
    else:
        print(f"  ❌ {tool:20s} - MISSING!")
        all_found = False

print("\n" + "=" * 60)

if all_found:
    print("✅ SUCCESS: All required FSM input tools are present!")
    print("\nThe agent should now properly transition between states.")
    print("Try saying: 'I want to book a haircut for tomorrow at 4:30 PM'")
else:
    print("❌ ERROR: Some FSM input tools are missing!")
    print("\nThe agent will remain stuck in START state.")

print("=" * 60)

# Also list all available function tools
print("\n📋 All available function tools in Assistant:\n")
for method_name in sorted(methods):
    method = getattr(assistant, method_name)
    if hasattr(method, '__wrapped__') or callable(method):
        # Try to get docstring
        doc = inspect.getdoc(method)
        if doc:
            first_line = doc.split('\n')[0]
            print(f"  • {method_name:30s} - {first_line[:50]}")

print("\n" + "=" * 60)
