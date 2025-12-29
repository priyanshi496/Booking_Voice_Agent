
import os
import httpx
import asyncio
import json
from dotenv import load_dotenv

load_dotenv(".env.local")

API_KEY = os.getenv("CAL_COM_API_KEY")

async def main():
    async with httpx.AsyncClient() as client:
        print("--- DEBUGGING V2 ---")
        try:
            res = await client.get(
                "https://api.cal.com/v2/event-types",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            print(f"Status: {res.status_code}")
            try:
                data = res.json()
                print(f"Response Keys: {list(data.keys())}")
                if "data" in data:
                    print(f"Data type: {type(data['data'])}")
                    if isinstance(data['data'], list) and len(data['data']) > 0:
                        print(f"First item type: {type(data['data'][0])}")
                        print(f"First item: {data['data'][0]}")
                    elif isinstance(data['data'], dict):
                        print(f"Data keys: {list(data['data'].keys())}")
                print("Full Response (first 500 chars):")
                print(json.dumps(data)[:500])
            except Exception as e:
                print(f"JSON Parse Error: {e}")
                print(f"Raw Text: {res.text[:500]}")
        except Exception as e:
            print(f"Request Error: {e}")

        print("\n--- DEBUGGING V1 ---")
        try:
            res = await client.get(
                "https://api.cal.com/v1/event-types",
                params={"apiKey": API_KEY}
            )
            print(f"Status: {res.status_code}")
            try:
                data = res.json()
                print(f"Full Response: {json.dumps(data)[:500]}")
            except Exception as e:
                print(f"JSON Parse Error: {e}")
        except Exception as e:
             print(f"Request Error: {e}")

if __name__ == "__main__":
    import sys
    # Redirect stdout to a file
    with open("debug_cal_output.txt", "w") as f:
        sys.stdout = f
        asyncio.run(main())
