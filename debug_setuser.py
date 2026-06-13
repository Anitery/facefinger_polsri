"""
Debug SetUserInfo - Melihat response XML asli dari X606-S
============================================================
"""
import http.client

IP = "192.168.0.177"
COM_KEY = "0"

def send_raw(xml_payload, label):
    print(f"\n{'='*60}")
    print(f"DEBUG: {label}")
    print(f"{'='*60}")
    print(f"Request XML:")
    print(xml_payload)
    print(f"\n{'-'*60}")

    try:
        conn = http.client.HTTPConnection(IP, 80, timeout=5)
        headers = {"Content-Type": "text/xml", "Content-Length": len(xml_payload)}
        conn.request("POST", "/iWsService", body=xml_payload, headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="ignore")
        conn.close()

        print(f"Status: {resp.status} {resp.reason}")
        print(f"\nResponse Body (RAW):")
        print(body)
        print(f"\n{'-'*60}")

        # Parse body
        if "\r\n\r\n" in body:
            _, body_part = body.split("\r\n\r\n", 1)
        elif "\n\n" in body:
            _, body_part = body.split("\n\n", 1)
        else:
            body_part = body

        print(f"Parsed Body:")
        print(body_part)
        return body_part
    except Exception as e:
        print(f"ERROR: {e}")
        return None

# 1. Cek user existing
xml1 = f'<GetAllUserInfo><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey></GetAllUserInfo>'
send_raw(xml1, "GetAllUserInfo (Cek User Existing)")

# 2. SetUserInfo dengan PIN baru (00001)
xml2 = f'<SetUserInfo><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey><Arg><PIN>00001</PIN><Name>Budi Santoso</Name><Privilege>0</Privilege><TZ1>0000-2359</TZ1><TZ2></TZ2><TZ3></TZ3></Arg></SetUserInfo>'
body2 = send_raw(xml2, "SetUserInfo (PIN 00001 - Budi Santoso)")

# 3. SetUserInfo dengan PIN baru (00002)
xml3 = f'<SetUserInfo><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey><Arg><PIN>00002</PIN><Name>Ani Wijaya</Name><Privilege>0</Privilege><TZ1>0000-2359</TZ1><TZ2></TZ2><TZ3></TZ3></Arg></SetUserInfo>'
body3 = send_raw(xml3, "SetUserInfo (PIN 00002 - Ani Wijaya)")

# 4. Cek user setelah set
xml4 = f'<GetAllUserInfo><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey></GetAllUserInfo>'
send_raw(xml4, "GetAllUserInfo (Setelah SetUserInfo)")

# 5. RefreshDB
xml5 = f'<RefreshDB><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey></RefreshDB>'
send_raw(xml5, "RefreshDB")

# 6. Coba GetUserInfo untuk PIN 00001
xml6 = f'<GetUserInfo><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey><Arg><PIN xsi:type="xsd:integer">00001</PIN></Arg></GetUserInfo>'
send_raw(xml6, "GetUserInfo (PIN 00001)")

# 7. Coba GetUserInfo untuk PIN 10 (TestUser)
xml7 = f'<GetUserInfo><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey><Arg><PIN xsi:type="xsd:integer">10</PIN></Arg></GetUserInfo>'
send_raw(xml7, "GetUserInfo (PIN 10 - TestUser)")

print(f"\n{'='*60}")
print("DEBUG SELESAI")
print(f"{'='*60}")
