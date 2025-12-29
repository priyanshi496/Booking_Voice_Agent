import os
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv(".env.local")

API_KEY = os.getenv("CAL_COM_API_KEY")

async def main():
    output_lines = []
    async with httpx.AsyncClient() as client:
        # Try v2 first
        try:
            res = await client.get(
                "https://api.cal.com/v2/event-types",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            output_lines.append(f"V2 Status: {res.status_code}")
            if res.status_code == 200:
                data = res.json()
                output_lines.append("V2 Event Types:")
                for et in data.get("data", []):
                    output_lines.append(f"- {et.get('slug')} (ID: {et.get('id')})")
            else:
                output_lines.append(f"V2 Error: {res.text}")
        except Exception as e:
            output_lines.append(f"V2 Exception: {e}")
        
        # Try v1
        try:
            res_v1 = await client.get(
                "https://api.cal.com/v1/event-types",
                params={"apiKey": API_KEY}
            )
            output_lines.append(f"\nV1 Status: {res_v1.status_code}")
            if res_v1.status_code == 200:
                 data = res_v1.json()
                 output_lines.append("V1 Event Types:")
                 for et in data.get("eventTypes", []):
                     output_lines.append(f"- {et.get('slug')} (ID: {et.get('id')})")
            else:
                output_lines.append(f"V1 Error: {res_v1.text}")
        except Exception as e:
            output_lines.append(f"V1 Exception: {e}")

    with open("slugs_output.txt", "w") as f:
        f.write("\n".join(output_lines))

if __name__ == "__main__":
    asyncio.run(main())
