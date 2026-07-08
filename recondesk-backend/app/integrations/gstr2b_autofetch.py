import os
import httpx

BASE_URL = "https://api.sandbox.co.in"
API_KEY = os.getenv("SANDBOX_API_KEY")
API_SECRET = os.getenv("SANDBOX_API_SECRET")


def get_sandbox_token() -> str:
    r = httpx.post(f"{BASE_URL}/authenticate", headers={
        "x-api-key": API_KEY,
        "x-api-secret": API_SECRET,
        "x-api-version": "1.0.0",
    })
    return r.json()["data"]["access_token"]


def send_otp(sandbox_token: str, gstin: str, username: str):
    r = httpx.post(f"{BASE_URL}/gst/compliance/tax-payer/otp",
        headers={
            "authorization": sandbox_token,
            "x-api-key": API_KEY,
            "x-api-version": "1.0.0",
            "x-source": "primary",
        },
        json={"gstin": gstin, "username": username})
    r.raise_for_status()
    return r.json()


def verify_otp(sandbox_token: str, gstin: str, username: str, otp: str) -> dict:
    r = httpx.post(f"{BASE_URL}/gst/compliance/tax-payer/otp/verify",
        headers={
            "authorization": sandbox_token,
            "x-api-key": API_KEY,
            "x-api-version": "1.0.0",
            "x-source": "primary",
        },
        json={"gstin": gstin, "username": username, "otp": otp})
    r.raise_for_status()
    return r.json()["data"]


def refresh_token(access_token: str) -> dict:
    r = httpx.post(f"{BASE_URL}/gst/compliance/tax-payer/session/refresh",
        headers={
            "authorization": access_token,
            "x-api-key": API_KEY,
            "x-api-version": "1.0.0",
        })
    r.raise_for_status()
    return r.json()["data"]


def get_gstr2b(access_token: str, gstin: str, year: str, month: str) -> dict:
    r = httpx.get(f"{BASE_URL}/gst/compliance/tax-payer/gstr2b/document",
        headers={
            "authorization": access_token,
            "x-api-key": API_KEY,
            "x-api-version": "1.0.0",
        },
        params={"gstin": gstin, "year": year, "month": month})
    r.raise_for_status()
    return r.json()["data"]
