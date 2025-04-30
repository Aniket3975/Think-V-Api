import requests
import time
import random
import argparse

def simulate_device(channel_id, api_key, interval=5):
    """Simulate an IoT device sending data to the platform"""
    print(f"Starting device simulation for channel {channel_id}")
    print(f"Press Ctrl+C to stop")
    
    base_url = f"http://localhost:8000/update"
    
    try:
        while True:
            # Generate random data
            temperature = 20 + random.uniform(-5, 5)
            humidity = 50 + random.uniform(-10, 10)
            pressure = 1013 + random.uniform(-5, 5)
            battery = min(100, max(0, 95 + random.uniform(-1, 0.5)))
            
            # Send data to the API
            params = {
                "channel_id": channel_id,
                "api_key": api_key,
                "field1": round(temperature, 2),
                "field2": round(humidity, 2),
                "field3": round(pressure, 2),
                "field4": round(battery, 2)
            }
            
            response = requests.get(base_url, params=params)
            
            if response.status_code == 200:
                print(f"Data sent: Temp={params['field1']}°C, Humidity={params['field2']}%, "
                      f"Pressure={params['field3']}hPa, Battery={params['field4']}%")
            else:
                print(f"Error sending data: {response.text}")
            
            # Wait for the specified interval
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("Simulation stopped")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IoT Device Simulator")
    parser.add_argument("channel_id", help="Channel ID to send data to")
    parser.add_argument("api_key", help="API key for the channel")
    parser.add_argument("--interval", type=int, default=5, help="Interval between data points in seconds")
    
    args = parser.parse_args()
    simulate_device(args.channel_id, args.api_key, args.interval)
