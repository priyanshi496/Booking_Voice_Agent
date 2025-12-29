
import sys
import os
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from booking import parse_datetime

def test(date_str, time_str):
    print(f"Testing Date: '{date_str}', Time: '{time_str}'")
    try:
        res = parse_datetime(date_str, time_str)
        print(f"  Result: {res}")
    except Exception as e:
        print(f"  Error: {e}")

# Test cases
test("2024-12-20", "17:00")
test("2024-12-20", "5:00 PM")
test("2024-12-20", "5 pm")
test("2024-12-20", "5pm")
test("2024-12-20", "5.30 pm")
test("tomorrow", "10 am")
test(None, "10 am")
test("2024-12-20", "10") # "at 10" often passed as "10"
test("Next Friday", "10:00")
