import asyncio
import time

import httpx
import requests


async def send_all(users):
    for user in users:
        requests.post("https://push.example.com/send", json={"to": user.id})  # expect: performance
        time.sleep(0.2)  # expect: performance


async def send_all_fast(users):
    async with httpx.AsyncClient() as client:
        await asyncio.gather(*(client.post("https://push.example.com/send", json={"to": u.id}) for u in users))


def build_report(rows):
    report = ""
    for row in rows:
        report += f"{row.name}: {row.total}\n"  # expect: performance
    return report


def build_report_fast(rows):
    return "".join(f"{row.name}: {row.total}\n" for row in rows)
