"""
Mock CRM data for collection flow POC.

In production, replace MOCK_CUSTOMER with a CRM API call that returns
customer data based on phone number / contract number from the inbound session.
"""

MOCK_CUSTOMER: dict[str, str | int] = {
    # ── ข้อมูลลูกค้า ─────────────────────────────────────────────────────
    "customer_name": "สมชาย ใจดี",
    "first_name": "สมชาย",
    "phone": "0812345678",

    # ── ข้อมูลรถ ──────────────────────────────────────────────────────────
    "car_brand_name": "Toyota",
    "car_model_name": "Yaris Ativ",
    "lic_no": "กข 1234",
    "province": "กรุงเทพมหานคร",

    # ── ข้อมูลหนี้ ────────────────────────────────────────────────────────
    "due_date": "5 มีนาคม 2568",        # งวดที่ค้างชำระ
    "due_amount": "8,500",              # ยอดค้างชำระ (บาท)
    "ptp_date": "31 มีนาคม 2568",      # วันนัดชำระ default ที่จะเสนอ
    "deadline": "2 เมษายน 2568",       # วันสุดท้ายก่อนถูกดำเนินการ

    # ── metadata สำหรับระบบ ───────────────────────────────────────────────
    "contract_no": "CHJ-2024-001234",
    "oa_code": "A888",
    "call_attempt": 1,                  # ครั้งที่โทรหา
}
