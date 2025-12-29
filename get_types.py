import os
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv(".env.local")
API_KEY = os.getenv("CAL_COM_API_KEY")

async def main():
    async with httpx.AsyncClient() as client:
        # Get Event Types v1
        print(f"Fetching event types with key: {API_KEY[:5]}...")
        resp = await client.get(
            "https://api.cal.com/v1/event-types",
            params={"apiKey": API_KEY}
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            types = resp.json().get("eventTypes", [])
            for t in types:
                print(f"Slug: {t.get('slug')} | ID: {t.get('id')} | Length: {t.get('length')}")

if __name__ == "__main__":
    asyncio.run(main())
