# Jalankan di laptop lokal: python check_device_users.py
import sys
sys.path.insert(0, ".")
from app.services.x606_soap import X606SOAPClient

client = X606SOAPClient(ip="192.168.0.177")
users = client.get_all_users()

print(f"\nUser di device ({len(users)} total):")
print(f"{'PIN':>6}  {'Name':<30}  {'PIN2':<10}  TZ1")
print("-" * 60)
for u in users:
    print(
        f"{u.get('PIN','?'):>6}  "
        f"{u.get('Name','?'):<30}  "
        f"{u.get('PIN2','?'):<10}  "
        f"{u.get('TZ1','?')}"
    )