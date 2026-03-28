"""
Collection flow for Ngern Hai Jai (บริษัทเงินให้ใจจำกัด)
AI Agent: น้องใจ (Nong Jai)

Flow:
  opening → verify → overdue → PTP → thank_you → end
                                └→ convince → PTP or refused → end
            └→ busy → end
            └→ other_person → end
  Any node → voicemail → end
  Any node (retry exceed) → fallback → end

State variables (injected from CRM via flow_manager.state):
  customer_name, first_name, lic_no, province,
  due_date, due_amount, ptp_date, deadline
"""

from pipecat_flows import FlowArgs, FlowManager, FlowResult, FlowsFunctionSchema, NodeConfig

# ---------------------------------------------------------------------------
# Helper: format prompt string from flow_manager.state
# ---------------------------------------------------------------------------


def _fmt(template: str, state: dict) -> str:
    """Safe string format — missing keys are left as-is."""
    try:
        return template.format(**state)
    except KeyError:
        return template


# ---------------------------------------------------------------------------
# Handler functions — each returns (FlowResult, next NodeConfig)
# ---------------------------------------------------------------------------


async def _handle_opening_response(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Decide next node from opening greeting."""
    response = args.get("response_type", "target")
    flow_manager.state["opening_response"] = response

    s = flow_manager.state
    if response == "target":
        return FlowResult(status="success"), create_verify_node(s)
    elif response == "busy":
        return FlowResult(status="success"), create_busy_node(s)
    elif response == "other_person":
        return FlowResult(status="success"), create_other_person_node(s)
    elif response == "voicemail":
        return FlowResult(status="success"), create_voicemail_node(s)
    return FlowResult(status="success"), create_fallback_node(s)


async def _handle_verify_response(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Confirm customer identity then move to overdue."""
    confirmed = args.get("confirmed", False)
    flow_manager.state["identity_confirmed"] = confirmed

    s = flow_manager.state
    if confirmed:
        return FlowResult(status="success"), create_overdue_node(s)
    return FlowResult(status="success"), create_fallback_node(s)


async def _handle_overdue_response(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Handle customer's response about overdue payment."""
    status = args.get("payment_status", "not_paid")
    flow_manager.state["payment_status"] = status

    s = flow_manager.state
    if status == "already_paid":
        return FlowResult(status="success"), create_paid_node(s)
    elif status == "agree_to_pay":
        return FlowResult(status="success"), create_ptp_node(s)
    elif status == "refuse":
        return FlowResult(status="success"), create_convince_node(s)
    return FlowResult(status="success"), create_fallback_node(s)


async def _handle_ptp_response(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Record Promise-to-Pay date and confirm."""
    ptp_date = args.get("ptp_date", flow_manager.state.get("ptp_date", ""))
    ptp_amount = args.get("ptp_amount", flow_manager.state.get("due_amount", ""))
    flow_manager.state["ptp_date"] = ptp_date
    flow_manager.state["ptp_amount"] = ptp_amount
    flow_manager.state["result_code"] = "PTP"
    return FlowResult(status="success"), create_thank_you_node(flow_manager.state)


async def _handle_convince_response(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Persuade customer to pay; handle agree or final refuse."""
    agreed = args.get("agreed", False)
    flow_manager.state["convinced"] = agreed

    s = flow_manager.state
    if agreed:
        return FlowResult(status="success"), create_ptp_node(s)
    flow_manager.state["result_code"] = "REFUSE"
    return FlowResult(status="success"), create_refused_node(s)


async def _handle_busy_response(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Record callback time preference and end."""
    flow_manager.state["callback_time"] = args.get("callback_time", "")
    flow_manager.state["result_code"] = "MSG"
    return FlowResult(status="success"), create_end_node()


async def _handle_other_person_response(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Leave message with third party and end."""
    flow_manager.state["message_left"] = args.get("message_left", True)
    flow_manager.state["result_code"] = "MSG"
    return FlowResult(status="success"), create_end_node()


async def _handle_wrap_up(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Wrap up after thank-you and close call."""
    flow_manager.state.setdefault("result_code", "REACHED")
    return FlowResult(status="success"), create_end_node()


# ---------------------------------------------------------------------------
# FlowsFunctionSchema definitions
# ---------------------------------------------------------------------------

opening_response_func = FlowsFunctionSchema(
    name="opening_response",
    description=(
        "Classify who answered the call: "
        "'target' = the customer themselves, "
        "'busy' = customer is unavailable right now, "
        "'other_person' = someone else answered, "
        "'voicemail' = answering machine detected"
    ),
    properties={
        "response_type": {
            "type": "string",
            "enum": ["target", "busy", "other_person", "voicemail"],
            "description": "Who answered the phone",
        }
    },
    required=["response_type"],
    handler=_handle_opening_response,
)

verify_response_func = FlowsFunctionSchema(
    name="verify_response",
    description="Record whether the customer confirmed their identity and vehicle registration",
    properties={
        "confirmed": {
            "type": "boolean",
            "description": "True if the customer confirmed they are the owner of the vehicle",
        }
    },
    required=["confirmed"],
    handler=_handle_verify_response,
)

overdue_response_func = FlowsFunctionSchema(
    name="overdue_response",
    description=(
        "Record customer's response about the overdue payment: "
        "'already_paid' = customer says they already paid, "
        "'agree_to_pay' = customer agrees to pay, "
        "'refuse' = customer refuses or is unable to pay"
    ),
    properties={
        "payment_status": {
            "type": "string",
            "enum": ["already_paid", "agree_to_pay", "refuse"],
            "description": "Customer's payment intention",
        }
    },
    required=["payment_status"],
    handler=_handle_overdue_response,
)

ptp_response_func = FlowsFunctionSchema(
    name="ptp_response",
    description="Record the Promise-to-Pay date and amount confirmed by the customer",
    properties={
        "ptp_date": {
            "type": "string",
            "description": "Date the customer promises to pay (e.g., '31 มีนาคม 2568')",
        },
        "ptp_amount": {
            "type": "string",
            "description": "Amount the customer promises to pay in baht",
        },
    },
    required=["ptp_date"],
    handler=_handle_ptp_response,
)

convince_response_func = FlowsFunctionSchema(
    name="convince_response",
    description="Record whether the customer agreed to pay after persuasion attempt",
    properties={
        "agreed": {
            "type": "boolean",
            "description": "True if the customer agreed to pay after persuasion",
        }
    },
    required=["agreed"],
    handler=_handle_convince_response,
)

busy_response_func = FlowsFunctionSchema(
    name="busy_response",
    description="Record the customer's preferred callback time",
    properties={
        "callback_time": {
            "type": "string",
            "description": "Preferred callback time provided by the customer or third party",
        }
    },
    required=["callback_time"],
    handler=_handle_busy_response,
)

other_person_response_func = FlowsFunctionSchema(
    name="other_person_response",
    description="Record that a message was left with the third party who answered",
    properties={
        "message_left": {
            "type": "boolean",
            "description": "True if the third party agreed to pass the message",
        }
    },
    required=["message_left"],
    handler=_handle_other_person_response,
)

wrap_up_func = FlowsFunctionSchema(
    name="wrap_up",
    description="Close the conversation after completing thank-you",
    properties={},
    required=[],
    handler=_handle_wrap_up,
)

# ---------------------------------------------------------------------------
# Shared system role
# ---------------------------------------------------------------------------

ROLE_CONTENT = (
    "คุณคือ น้องใจ เจ้าหน้าที่อัตโนมัติจากบริษัทเงินให้ใจจำกัด "
    "กฎที่ต้องปฏิบัติตามเคร่งครัด: "
    "1. ส่วนที่ระบุว่า [บทพูด] คือประโยคที่ต้องพูดคำต่อคำ ห้ามดัดแปลง ห้ามย่อ ห้ามเพิ่มคำ "
    "2. พูดสุภาพ อ่อนโยน เป็นมืออาชีพ ใช้ภาษาไทยทางการ "
    "3. ห้ามเปิดเผยยอดหนี้หรือข้อมูลสัญญากับบุคคลอื่นที่ไม่ใช่ลูกค้า "
    "4. หากลูกค้าไม่ตอบสนองสองครั้งติดต่อกัน ให้ call wrap_up แล้วจบสาย "
    "5. ตอบสนองต่อสิ่งที่ลูกค้าพูดเท่านั้น ห้าม improvise หรือเพิ่มข้อมูลที่ไม่มีใน script"
)


def _role_messages() -> list[dict]:
    return [{"role": "system", "content": ROLE_CONTENT}]


# ---------------------------------------------------------------------------
# Node factory functions — all accept `state: dict` for prompt formatting
# ---------------------------------------------------------------------------


def create_opening_node(state: dict | None = None) -> NodeConfig:
    """Initial greeting — identify who answered."""
    s = state or {}
    return NodeConfig(
        name="opening",
        role_messages=_role_messages(),
        task_messages=[
            {
                "role": "system",
                "content": _fmt(
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'สวัสดีค่ะ ดิฉัน น้องใจ, จากบริษัทเงินให้ใจจำกัด ขอเรียนสาย คุณ {customer_name}, ค่ะ'\n"
                    "ถ้าลูกค้าไม่แน่ใจหรือถามว่าใคร ให้พูดเพิ่ม:\n"
                    "'ไม่ทราบว่าดิฉันกำลังเรียนสายกับ คุณ {customer_name} อยู่หรือเปล่าคะ'\n\n"
                    "[หลังจากพูด] รอฟังเสียงตอบรับ แล้วประเมินและ call opening_response ด้วย response_type ที่ตรงที่สุด:\n"
                    "- 'target' = ลูกค้าตอบรับและระบุว่าคือ {customer_name} หรือไม่ได้ปฏิเสธ\n"
                    "- 'target' = ลูกค้าบอกว่าไม่ว่าง หรือขอโทรกลับ\n"
                    "- 'other_person' = คนอื่นรับสายแทน\n"
                    "- 'voicemail' = เป็นระบบตอบรับอัตโนมัติ",
                    s,
                ),
            }
        ],
        functions=[opening_response_func],
        respond_immediately=True,
    )


def create_verify_node(state: dict | None = None) -> NodeConfig:
    """Verify customer identity via vehicle registration."""
    s = state or {}
    return NodeConfig(
        name="verify",
        task_messages=[
            {
                "role": "system",
                "content": _fmt(
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'ขอบคุณค่ะ น้องใจขออนุญาตยืนยันข้อมูลนะคะ "
                    "คุณ {first_name} เป็นเจ้าของรถทะเบียน {lic_no}, {province} ใช่ไหมคะ?'\n\n"
                    "[หลังจากพูด] รอฟังคำตอบ แล้ว call verify_response:\n"
                    "- confirmed=true ถ้าลูกค้าตอบว่าใช่ หรือไม่ปฏิเสธ\n"
                    "- confirmed=false ถ้าลูกค้าบอกว่าไม่ใช่หรือไม่แน่ใจ",
                    s,
                ),
            }
        ],
        functions=[verify_response_func],
    )


def create_overdue_node(state: dict | None = None) -> NodeConfig:
    """Inform customer of overdue amount and ask payment status."""
    s = state or {}
    return NodeConfig(
        name="overdue",
        task_messages=[
            {
                "role": "system",
                "content": _fmt(
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'ขอบคุณค่ะ ทั้งนี้ เพื่อพัฒนาคุณภาพการให้บริการ "
                    "ทางบริษัทฯ จะมีการบันทึกเสียงการสนทนานะคะ "
                    "วันนี้น้องใจขออนุญาตติดต่อ เรื่องสินเชื่อรถ ทะเบียน {lic_no}, {province}ค่ะ "
                    "คือน้องใจจะรบกวนสอบถามเรื่องยอดเรียกเก็บในเดือนปัจจุบัน '\n"
                    "แล้วต่อด้วย: 'ไม่ทราบว่าคุณลูกค้าได้ชำระเข้ามาแล้วหรือยังคะ'\n\n"
                    "[หลังจากพูด] รอฟังคำตอบ แล้ว call overdue_response:\n"
                    "- already_paid = ลูกค้าบอกว่าชำระแล้ว\n"
                    "- agree_to_pay = ลูกค้ายังไม่ชำระและตกลงจะชำระ\n"
                    "- refuse = ลูกค้าปฏิเสธหรือบอกว่าไม่มีเงิน",
                    s,
                ),
            }
        ],
        functions=[overdue_response_func],
    )


def create_ptp_node(state: dict | None = None) -> NodeConfig:
    """Secure a Promise-to-Pay commitment."""
    s = state or {}
    return NodeConfig(
        name="ptp",
        task_messages=[
            {
                "role": "system",
                "content": _fmt(
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'ขอบคุณมากค่ะ งั้นน้องใจรบกวนคุณลูกค้าชำระยอด {due_amount} บาท "
                    "ภายในวันที่ {ptp_date} นะคะ ไม่ทราบว่าสะดวกไหมคะ?'\n\n"
                    "[หลังจากพูด] รอฟังการยืนยัน ถ้าลูกค้าตกลง ให้ call ptp_response "
                    "พร้อม ptp_date={ptp_date} และ ptp_amount={due_amount} "
                    "ถ้าลูกค้าขอเปลี่ยนวัน ให้ใช้วันที่ลูกค้าระบุเป็น ptp_date แทน",
                    s,
                ),
            }
        ],
        functions=[ptp_response_func],
    )


def create_convince_node(state: dict | None = None) -> NodeConfig:
    """Persuade customer who initially refused to pay."""
    s = state or {}
    return NodeConfig(
        name="convince",
        task_messages=[
            {
                "role": "system",
                "content": _fmt(
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'น้องใจขอแจ้งยอดเรียกเก็บนะคะ "
                    "ยอดที่แจ้งรวมค่าปรับและค่าติดตามทวงถามหนี้เป็นจำนวน {due_amount} บาท '\n"
                    "แล้วต่อด้วย: 'กรุณาชำระภายในวันนี้ สะดวกไหมคะ'\n"
                    "ถ้าลูกค้ายังปฏิเสธ ให้พูดเพิ่ม:\n"
                    "'เพื่อรักษาเครดิตและประวัติการชำระ น้องใจขอแนะนำให้คุณลูกค้าชำระเงินภายในวันพรุ่งนี้ค่ะ "
                    "การชำระจะช่วยให้ภาระค่าใช้จ่ายในอนาคตของคุณลูกค้าลดลงด้วยนะคะ "
                    "กรุณาชำระเข้ามาภายในวันพรุ่งนี้ได้ไหมคะ'\n\n"
                    "[หลังจากพูด] รอฟังคำตอบ แล้ว call convince_response:\n"
                    "- agreed=true ถ้าลูกค้าตกลงหรือบอกว่าจะลอง\n"
                    "- agreed=false ถ้าลูกค้าปฏิเสธหรือไม่สามารถชำระได้",
                    s,
                ),
            }
        ],
        functions=[convince_response_func],
    )


def create_busy_node(state: dict | None = None) -> NodeConfig:
    """Handle situation where customer is currently busy."""
    return NodeConfig(
        name="busy",
        task_messages=[
            {
                "role": "system",
                "content": (
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'ขออภัยที่รบกวนเวลาค่ะ ไม่ทราบว่าสะดวกให้ติดต่อกลับมาอีกครั้งเวลาไหนดีคะ?'\n\n"
                    "[หลังจากพูด] รอฟังเวลาที่ลูกค้าระบุ แล้ว call busy_response พร้อม callback_time "
                    "เช่น '14:00' หรือ 'บ่ายสองโมง' หรือ 'พรุ่งนี้เช้า'"
                ),
            }
        ],
        functions=[busy_response_func],
    )


def create_other_person_node(state: dict | None = None) -> NodeConfig:
    """Handle third-party answering the call."""
    s = state or {}
    return NodeConfig(
        name="other_person",
        task_messages=[
            {
                "role": "system",
                "content": _fmt(
                    "บุคคลอื่นรับสาย ห้ามเปิดเผยยอดหนี้ ให้ฝากข้อความเท่านั้น: "
                    "'ไม่ทราบว่าพอจะสะดวกแจ้งช่องทางติดต่อ หรือฝากถึงคุณ {customer_name} "
                    "ว่าน้องใจโทรมาเรื่องสำคัญ ขอให้ติดต่อกลับได้ไหมคะ?' "
                    "แล้ว call other_person_response พร้อม message_left",
                    s,
                ),
            }
        ],
        functions=[other_person_response_func],
    )


def create_paid_node(state: dict | None = None) -> NodeConfig:
    """Acknowledge customer who has already paid."""
    return NodeConfig(
        name="paid",
        task_messages=[
            {
                "role": "system",
                "content": (
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'น้องใจขอขอบคุณสำหรับการชำระเงินและใช้บริการบริษัทเงินให้ใจจำกัด "
                    "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ สวัสดีค่ะ'\n\n"
                    "[หลังจากพูด] call wrap_up ทันที"
                ),
            }
        ],
        functions=[wrap_up_func],
    )


def create_voicemail_node(state: dict | None = None) -> NodeConfig:
    """Leave a message on voicemail/answering machine."""
    s = state or {}
    return NodeConfig(
        name="voicemail",
        task_messages=[
            {
                "role": "system",
                "content": _fmt(
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'ขออนุญาตติดต่อใหม่ภายหลังนะคะ, สวัสดีค่ะ'\n\n"
                    "[หลังจากพูด] call wrap_up ทันที",
                    s,
                ),
            }
        ],
        functions=[wrap_up_func],
    )


def create_thank_you_node(state: dict | None = None) -> NodeConfig:
    """Thank the customer and close after PTP is secured."""
    s = state or {}
    return NodeConfig(
        name="thank_you",
        task_messages=[
            {
                "role": "system",
                "content": _fmt(
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'น้องใจขอบคุณที่ใช้บริการบริษัทเงินให้ใจจำกัด "
                    "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ สวัสดีค่ะ'\n\n"
                    "[หลังจากพูด] call wrap_up ทันที",
                    s,
                ),
            }
        ],
        functions=[wrap_up_func],
    )


def create_refused_node(state: dict | None = None) -> NodeConfig:
    """Close call politely after customer finally refuses."""
    return NodeConfig(
        name="refused",
        task_messages=[
            {
                "role": "system",
                 "content": (
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'หากลูกค้ายังไม่สะดวก ไม่เป็นไรค่ะ น้องใจขออนุญาตติดต่อหาลูกค้าอีกครั้งนะคะ "
                    "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ "
                    "ขอบคุณที่ใช้บริการบริษัทเงินให้ใจจำกัด สวัสดีค่ะ'\n\n"
                    "[หลังจากพูด] call wrap_up ทันที"
                ),
            }
        ],
        functions=[wrap_up_func],
    )


def create_fallback_node(state: dict | None = None) -> NodeConfig:
    """Handle no-response or repeated misunderstandings."""
    return NodeConfig(
        name="fallback",
        task_messages=[
            {
                "role": "system",
                 "content": (
                    "[บทพูด] พูดประโยคนี้คำต่อคำ:\n"
                    "'ขออภัยคะ น้องใจ จะแจ้งให้เจ้าหน้าที่ติดต่อกลับอีกครั้ง สวัสดีค่ะ'\n\n"
                    "[หลังจากพูด] call wrap_up ทันที"
                ),
            }
        ],
        functions=[wrap_up_func],
    )


def create_end_node() -> NodeConfig:
    """End the conversation."""
    return NodeConfig(
        name="end",
        task_messages=[],
        functions=[],
        post_actions=[{"type": "end_conversation"}],
    )


# ---------------------------------------------------------------------------
# Entry point — called by flow registry with no state yet
# (state will be injected by bot.py before flow_manager.initialize())
# ---------------------------------------------------------------------------


def create_initial_node(state: dict | None = None) -> NodeConfig:
    """Return the first node of the collection flow."""
    return create_opening_node(state or {})
