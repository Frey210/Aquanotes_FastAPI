import requests
import random
import time
from datetime import datetime, timedelta, timezone

# Konstanta
URL = "https://aeraseaku.inkubasistartupunhas.id/sensor/"
UID = "AER2023AQ0001"
UTC_PLUS_8 = timezone(timedelta(hours=8))  # UTC+8 timezone

def generate_random_sensor_data():
    return {
        "uid": UID,
        "suhu": round(random.uniform(25.0, 35.0), 2),         # suhu dalam °C
        "ph": round(random.uniform(6.5, 8.5), 2),              # pH netral ke alkali
        "do": round(random.uniform(4.0, 10.0), 2),             # DO (mg/L)
        "tds": round(random.uniform(200.0, 1500.0), 2),        # TDS (ppm)
        "ammonia": round(random.uniform(0.0, 0.5), 3),         # Ammonia (mg/L)
        "salinitas": round(random.uniform(5.0, 35.0), 2),      # Salinitas (ppt)
        "timestamp": datetime.now(UTC_PLUS_8).isoformat()
    }

def send_sensor_data():
    while True:
        data = generate_random_sensor_data()
        try:
            response = requests.post(URL, json=data, headers={"accept": "application/json"})
            print(f"[{datetime.now()}] Sent. Status: {response.status_code}, Response: {response.text}")
        except Exception as e:
            print(f"[{datetime.now()}] Error: {e}")
        time.sleep(60)  # Kirim setiap 1 menit

if __name__ == "__main__":
    send_sensor_data()
