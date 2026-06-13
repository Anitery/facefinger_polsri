"""
X606-S Debug Script - Melihat Response XML Asli dari Device
============================================================
Gunakan ini untuk debug parsing XML dan melihat format response asli.
"""
import http.client

IP = "192.168.0.177"  # GANTI dengan IP X606-S Anda
COM_KEY = "0"

def send_raw_and_show(xml_payload, label):
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
        print(f"Headers: {dict(resp.getheaders())}")
        print(f"\nResponse Body (RAW):")
        print(body)
        print(f"\n{'-'*60}")

        # Parse HTTP body (pisah header dari body jika ada)
        if "\r\n\r\n" in body:
            headers_part, body_part = body.split("\r\n\r\n", 1)
            print(f"Parsed Body:")
            print(body_part)
        elif "\n\n" in body:
            headers_part, body_part = body.split("\n\n", 1)
            print(f"Parsed Body:")
            print(body_part)
        else:
            body_part = body

        return body_part
    except Exception as e:
        print(f"ERROR: {e}")
        return None

# 1. Test GetDate (simplest)
xml1 = f'<GetDate><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey></GetDate>'
send_raw_and_show(xml1, "GetDate (Test Koneksi)")

# 2. Test GetAllUserInfo
xml2 = f'<GetAllUserInfo><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey></GetAllUserInfo>'
body = send_raw_and_show(xml2, "GetAllUserInfo (List User)")

# 3. Test GetAttLog (All)
xml3 = f'<GetAttLog><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey><Arg><PIN xsi:type="xsd:integer">All</PIN></Arg></GetAttLog>'
send_raw_and_show(xml3, "GetAttLog (All Logs)")

# 4. Test GetUserInfo untuk PIN 00001
xml4 = f'<GetUserInfo><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey><Arg><PIN xsi:type="xsd:integer">00001</PIN></Arg></GetUserInfo>'
send_raw_and_show(xml4, "GetUserInfo (PIN 00001)")

# 5. Test SetUserInfo (tambah user baru)
xml5 = f'<SetUserInfo><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey><Arg><PIN>00099</PIN><Name>TestUser</Name><TZ1>0000-2359</TZ1></Arg></SetUserInfo>'
send_raw_and_show(xml5, "SetUserInfo (Tambah User Test)")

# 6. RefreshDB
xml6 = f'<RefreshDB><ArgComKey xsi:type="xsd:integer">{COM_KEY}</ArgComKey></RefreshDB>'
send_raw_and_show(xml6, "RefreshDB")

print(f"\n{'='*60}")
print("DEBUG SELESAI")
print(f"{'='*60}")
