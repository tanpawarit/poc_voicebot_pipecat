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
        flow_manager.state["ptp_date"] = args.get("ptp_date", s.get("ptp_date", ""))
        flow_manager.state["ptp_amount"] = args.get("ptp_amount", s.get("due_amount", ""))
        flow_manager.state["result_code"] = "PTP"
        return FlowResult(status="success"), create_ptp_node(s)
    elif status == "refuse":
        flow_manager.state["convince_attempt"] = 1
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
        flow_manager.state["ptp_date"] = args.get("ptp_date", s.get("ptp_date", ""))
        flow_manager.state["ptp_amount"] = args.get("ptp_amount", s.get("due_amount", ""))
        flow_manager.state["result_code"] = "PTP"
        return FlowResult(status="success"), create_ptp_node(s)
    attempt = int(flow_manager.state.get("convince_attempt", 1))
    if attempt <= 1:
        flow_manager.state["convince_attempt"] = 2
        return FlowResult(status="success"), create_convince2_node(s)
    flow_manager.state["result_code"] = "REFUSE"
    return FlowResult(status="success"), create_refused_node(s)


async def _handle_busy_response(
    args: FlowArgs, flow_manager: FlowManager
) -> tuple[FlowResult, NodeConfig]:
    """Record callback time preference and end."""
    flow_manager.state["callback_time"] = args.get("callback_time", "")
    callback_bucket = args.get("callback_bucket", "today")
    flow_manager.state["callback_bucket"] = callback_bucket
    flow_manager.state["result_code"] = "MSG"
    if callback_bucket == "in_time":
        return FlowResult(status="success"), create_busy_in_time_node()
    if callback_bucket == "out_time":
        return FlowResult(status="success"), create_busy_out_time_node()
    return FlowResult(status="success"), create_busy_today_node()


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
        },
        "ptp_date": {
            "type": "string",
            "description": "Date the customer promises to pay when payment_status=agree_to_pay",
        },
        "ptp_amount": {
            "type": "string",
            "description": "Amount the customer promises to pay in baht when payment_status=agree_to_pay",
        },
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
        },
        "ptp_date": {
            "type": "string",
            "description": "Date the customer promises to pay when agreed=true",
        },
        "ptp_amount": {
            "type": "string",
            "description": "Amount the customer promises to pay in baht when agreed=true",
        },
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
        },
        "callback_bucket": {
            "type": "string",
            "enum": ["today", "in_time", "out_time"],
            "description": (
                "'today' if the requested time cannot be honored today, "
                "'in_time' if the requested callback is within serviceable hours, "
                "'out_time' if the requested callback is outside serviceable hours"
            ),
        }
    },
    required=["callback_time", "callback_bucket"],
    handler=_handle_busy_response,
)

other_person_response_func = FlowsFunctionSchema(
    name="other_person_response",
    description="Record whether a message was left with the third party who answered",
    properties={
        "message_left": {
            "type": "boolean",
            "description": "True if a message was left, false if the call was politely ended without leaving one",
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


def get_global_functions() -> list[FlowsFunctionSchema]:
    """Return the complete toolset to preload for Gemini Live.

    Gemini Live in the current Pipecat version ignores runtime LLMSetToolsFrame
    updates, so we keep the full callable set available for the whole session.
    """
    return [
        opening_response_func,
        verify_response_func,
        overdue_response_func,
        convince_response_func,
        busy_response_func,
        other_person_response_func,
        wrap_up_func,
    ]

# ---------------------------------------------------------------------------
# Shared system role
# ---------------------------------------------------------------------------

ROLE_CONTENT = (
    "คุณคือ น้องใจ เจ้าหน้าที่อัตโนมัติจากบริษัทเงินให้ใจจำกัด "
    "กฎที่ต้องปฏิบัติตามเคร่งครัด: "
    "1. เมื่อมีหัวข้อ [SCRIPT_TEXT], [PRIMARY_SCRIPT_TEXT], หรือ [CONDITIONAL_SCRIPT_TEXT] "
    "ให้พูดเฉพาะข้อความในส่วนนั้นคำต่อคำเท่านั้น ห้ามดัดแปลง ห้ามย่อ ห้ามเพิ่มคำ "
    "2. ห้ามพูดหัวข้อกำกับ เช่น SCRIPT_ID, SCRIPT_TEXT, PRIMARY_SCRIPT_TEXT, "
    "CONDITIONAL_SCRIPT_TEXT, INSTRUCTIONS, AFTER_SPEAKING หรือคำอธิบายคำสั่งใดๆ ออกเสียง "
    "3. พูดสุภาพ อ่อนโยน เป็นมืออาชีพ ใช้ภาษาไทยทางการ "
    "4. ห้ามเปิดเผยยอดหนี้หรือข้อมูลสัญญากับบุคคลอื่นที่ไม่ใช่ลูกค้า "
    "5. หากลูกค้าไม่ตอบสนองสองครั้งติดต่อกัน ให้ call wrap_up แล้วจบสาย "
    "6. ตอบสนองต่อสิ่งที่ลูกค้าพูดเท่านั้น ห้าม improvise หรือเพิ่มข้อมูลที่ไม่มีใน script"
)

def _verbatim_task_content(
    *,
    script_id: str,
    script_text: str,
    after_speaking: str,
    state: dict | None = None,
) -> str:
    """Build a strict single-script task message."""
    s = state or {}
    return _fmt(
        "[SCRIPT_ID]\n"
        f"{script_id}\n\n"
        "[SCRIPT_TEXT]\n"
        f"{script_text}\n\n"
        "[INSTRUCTIONS]\n"
        "พูดเฉพาะข้อความใน [SCRIPT_TEXT] ด้านบนคำต่อคำเพียงครั้งเดียวเท่านั้น "
        "ห้ามพูดหัวข้อกำกับ ห้ามอธิบายคำสั่ง ห้ามดัดแปลง ห้ามย่อ ห้ามเพิ่มคำ และห้ามพูดข้อความอื่นนอก script\n\n"
        "[AFTER_SPEAKING]\n"
        f"{after_speaking}",
        s,
    )


def _conditional_verbatim_task_content(
    *,
    primary_script_id: str,
    primary_script_text: str,
    conditional_script_id: str,
    conditional_script_text: str,
    conditional_rule: str,
    after_speaking: str,
    state: dict | None = None,
) -> str:
    """Build a strict task message with an optional conditional follow-up script."""
    s = state or {}
    return _fmt(
        "[PRIMARY_SCRIPT_ID]\n"
        f"{primary_script_id}\n\n"
        "[PRIMARY_SCRIPT_TEXT]\n"
        f"{primary_script_text}\n\n"
        "[CONDITIONAL_SCRIPT_ID]\n"
        f"{conditional_script_id}\n\n"
        "[CONDITIONAL_SCRIPT_TEXT]\n"
        f"{conditional_script_text}\n\n"
        "[INSTRUCTIONS]\n"
        "เมื่อเข้า node นี้ ให้พูดเฉพาะ [PRIMARY_SCRIPT_TEXT] คำต่อคำเพียงครั้งเดียวก่อน แล้วหยุดรอฟังทันที "
        "ห้ามพูดหัวข้อกำกับ ห้ามอธิบายคำสั่ง ห้ามดัดแปลง ห้ามย่อ ห้ามเพิ่มคำ และห้ามพูดข้อความอื่นนอก script\n"
        f"ให้พูด [CONDITIONAL_SCRIPT_TEXT] ได้ก็ต่อเมื่อ {conditional_rule} เท่านั้น "
        "หากเงื่อนไขไม่เกิดขึ้น ห้ามพูด script สำรองนี้\n\n"
        "[AFTER_SPEAKING]\n"
        f"{after_speaking}",
        s,
    )


def _sequence_verbatim_task_content(
    *,
    scripts: list[tuple[str, str]],
    after_speaking: str,
    state: dict | None = None,
) -> str:
    """Build a strict task message with multiple scripts spoken in order."""
    s = state or {}
    script_sections = []
    for script_id, script_text in scripts:
        script_sections.append(f"[SCRIPT_ID]\n{script_id}\n\n[SCRIPT_TEXT]\n{script_text}")
    return _fmt(
        "\n\n".join(script_sections)
        + "\n\n[INSTRUCTIONS]\n"
        + "ให้พูดแต่ละ [SCRIPT_TEXT] ตามลำดับที่ปรากฏคำต่อคำเท่านั้น ห้ามข้าม ห้ามสลับลำดับ "
        + "ห้ามพูดหัวข้อกำกับ ห้ามอธิบายคำสั่ง ห้ามดัดแปลง ห้ามย่อ ห้ามเพิ่มคำ "
        + "และห้ามพูดข้อความอื่นนอก script\n\n"
        + "[AFTER_SPEAKING]\n"
        + after_speaking,
        s,
    )


def _task_message(content: str) -> dict:
    """Wrap node instructions as a user task so Gemini Live emits a response."""
    return {"role": "user", "content": content}


# ---------------------------------------------------------------------------
# Node factory functions — all accept `state: dict` for prompt formatting
# ---------------------------------------------------------------------------


def create_opening_node(state: dict | None = None) -> NodeConfig:
    """Initial greeting — identify who answered."""
    s = state or {}
    return NodeConfig(
        name="opening",
        task_messages=[
            _task_message(
                _conditional_verbatim_task_content(
                    primary_script_id="opening_01_1",
                    primary_script_text=(
                        "สวัสดีค่ะ ดิฉัน น้องใจ, จากบริษัทเงินให้ใจจำกัด "
                        "ขอเรียนสาย คุณ {customer_name}, ค่ะ"
                    ),
                    conditional_script_id="opening_01_r1",
                    conditional_script_text=(
                        "ไม่ทราบว่าดิฉันกำลังเรียนสายกับ คุณ {customer_name} "
                        "อยู่หรือเปล่าคะ"
                    ),
                    conditional_rule=(
                        "ลูกค้าแสดงว่าไม่แน่ใจว่าใครโทรมา หรือถามกลับว่าใครพูด"
                    ),
                    after_speaking=(
                        "รอฟังเสียงตอบรับ แล้ว call opening_response ด้วย response_type ที่ตรงที่สุด:\n"
                        "- 'target' = ลูกค้าตอบรับและระบุว่าคือ {customer_name} หรือไม่ได้ปฏิเสธ\n"
                        "- 'busy' = ลูกค้าบอกว่าไม่ว่าง หรือต้องการให้โทรกลับ\n"
                        "- 'other_person' = คนอื่นรับสายแทน\n"
                        "- 'voicemail' = เป็นระบบตอบรับอัตโนมัติ"
                    ),
                    state=s,
                ),
            )
        ],
        functions=[],
        respond_immediately=True,
    )


def create_verify_node(state: dict | None = None) -> NodeConfig:
    """Verify customer identity via vehicle registration."""
    s = state or {}
    return NodeConfig(
        name="verify",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="verify_01",
                    script_text=(
                        "ขอบคุณค่ะ น้องใจขอออนุญาตยืนยันข้อมูลนะคะ "
                        "คุณ{first_name} เป็นเจ้าของรถทะเบียน{lic_no}, {province}ใช่มั้ยคะ?"
                    ),
                    after_speaking=(
                        "รอฟังคำตอบ แล้ว call verify_response:\n"
                        "- confirmed=true ถ้าลูกค้าตอบว่าใช่ หรือไม่ปฏิเสธ\n"
                        "- confirmed=false ถ้าลูกค้าบอกว่าไม่ใช่หรือไม่แน่ใจ"
                    ),
                    state=s,
                ),
            )
        ],
        functions=[],
    )


def create_overdue_node(state: dict | None = None) -> NodeConfig:
    """Inform customer of overdue amount and ask payment status."""
    s = state or {}
    return NodeConfig(
        name="overdue",
        task_messages=[
            _task_message(
                _sequence_verbatim_task_content(
                    scripts=[
                        (
                            "overdue_01",
                            "ขอบคุณค่ะ ทั้งนี้ เพื่อพัฒนาคุณภาพการให้บริการ "
                            "ทางบริษัทฯ จะมีการบันทึกเสียงการสนทนานะคะ "
                            "วันนี้น้องใจขออนุญาตติดต่อ เรื่องสินเชื่อรถ "
                            "ทะเบียน{lic_no}, {province}ค่ะ "
                            "คือน้องใจจะรบกวนสอบถามเรื่องยอดเรียกเก็บในเดือนปัจจุบัน",
                        ),
                        (
                            "overdue_02",
                            "ไม่ทราบว่าคุณลูกค้าได้ชำระเข้ามาแล้วหรือยังคะ",
                        ),
                    ],
                    after_speaking=(
                        "รอฟังคำตอบ จากนั้น call overdue_response:\n"
                        "- already_paid = ลูกค้าบอกว่าชำระแล้ว\n"
                        "- agree_to_pay = ลูกค้ายังไม่ชำระและตกลงจะชำระ โดยถ้ามีวันหรือยอดให้ใส่ ptp_date และ ptp_amount\n"
                        "- refuse = ลูกค้าปฏิเสธหรือบอกว่าไม่มีเงิน"
                    ),
                    state=s,
                ),
            )
        ],
        functions=[],
    )


def create_ptp_node(state: dict | None = None) -> NodeConfig:
    """Close the call after PTP has already been captured."""
    return NodeConfig(
        name="ptp",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="ptp_01",
                    script_text=(
                        "น้องใจขอบคุณที่ใช้บริการบริษัทเงินให้ใจจำกัด "
                        "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 "
                        "ค่ะ สวัสดีค่ะ"
                    ),
                    after_speaking=(
                        "call wrap_up ทันที"
                    ),
                ),
            )
        ],
        functions=[],
    )


def create_convince_node(state: dict | None = None) -> NodeConfig:
    """First persuasion attempt after customer refuses to pay."""
    s = state or {}
    return NodeConfig(
        name="convince",
        task_messages=[
            _task_message(
                _sequence_verbatim_task_content(
                    scripts=[
                        (
                            "convince_01",
                            "น้องใจขอแจ้งยอดเรียกเก็บนะคะ "
                            "ยอดที่แจ้งรวมค่าปรับและค่าติดตามทวงถามหนี้เป็นจำนวน "
                            "{due_amount}บาท",
                        ),
                        (
                            "convince_02",
                            "กรุณาชำระภายในวันนี้ สะดวกไหมคะ",
                        ),
                    ],
                    after_speaking=(
                        "รอฟังคำตอบ แล้ว call convince_response:\n"
                        "- agreed=true ถ้าลูกค้าตกลงหรือบอกว่าจะชำระ โดยถ้ามีวันหรือยอดให้ใส่ ptp_date และ ptp_amount\n"
                        "- agreed=false ถ้าลูกค้าปฏิเสธหรือไม่สามารถชำระได้"
                    ),
                    state=s,
                ),
            )
        ],
        functions=[],
    )


def create_convince2_node(state: dict | None = None) -> NodeConfig:
    """Second persuasion attempt aligned to PDF convince2 script."""
    s = state or {}
    return NodeConfig(
        name="convince2",
        task_messages=[
            _task_message(
                _sequence_verbatim_task_content(
                    scripts=[
                        (
                            "convince2_01",
                            "เพื่อรักษาเครดิตและประวัติการชำระ "
                            "น้องใจขอแนะนำให้คุณลูกค้าชำระเงินภายในวันพรุ่งนี้ค่ะ "
                            "การชำระจะช่วยให้ภาระค่าใช้จ่ายในอนาคตของคุณลูกค้าลดลงด้วยนะคะ",
                        ),
                        (
                            "convince2_02",
                            "กรุณาชำระเข้ามาภายในวันพรุ่งนี้ได้ไหมคะ",
                        ),
                    ],
                    after_speaking=(
                        "รอฟังคำตอบ แล้ว call convince_response:\n"
                        "- agreed=true ถ้าลูกค้าตกลงหรือบอกว่าจะชำระ โดยถ้ามีวันหรือยอดให้ใส่ ptp_date และ ptp_amount\n"
                        "- agreed=false ถ้าลูกค้าปฏิเสธหรือไม่สามารถชำระได้"
                    ),
                    state=s,
                ),
            )
        ],
        functions=[],
    )


def create_busy_node(state: dict | None = None) -> NodeConfig:
    """Handle situation where customer is currently busy."""
    return NodeConfig(
        name="busy",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="busy_01",
                    script_text=(
                        "ขออภัยที่รบกวนเวลาค่ะ ไม่ทราบว่าสะดวกให้ติดต่อกลับมาอีกครั้งเวลาไหนดีคะ"
                    ),
                    after_speaking=(
                        "รอฟังเวลาที่ลูกค้าระบุ แล้ว call busy_response พร้อม callback_time "
                        "และ callback_bucket:\n"
                        "- 'today' ถ้าเวลาที่ลูกค้าแจ้งไม่สามารถให้บริการตามเวลานั้นได้ในวันนี้\n"
                        "- 'in_time' ถ้าเวลาที่ลูกค้าแจ้งอยู่ในช่วงที่สามารถติดต่อใหม่ตามวันและเวลาที่แจ้งได้\n"
                        "- 'out_time' ถ้าเวลาที่ลูกค้าแจ้งอยู่นอกเวลาทำการ"
                    ),
                ),
            )
        ],
        functions=[],
    )


def create_busy_today_node(state: dict | None = None) -> NodeConfig:
    """Close the busy flow when the requested callback time cannot be served today."""
    return NodeConfig(
        name="busy_today",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="busy_02a",
                    script_text=(
                        "เวลาลูกค้าแจ้งมา น้องใจ ไม่สามารถให้บริการตามเวลาลูกค้าแจ้งได้ "
                        "ขออนุญาตติดต่อใหม่ภายหลังนะคะ, สวัสดีค่ะ"
                    ),
                    after_speaking="call wrap_up ทันที",
                ),
            )
        ],
        functions=[],
    )


def create_busy_in_time_node(state: dict | None = None) -> NodeConfig:
    """Close the busy flow when the requested callback time is serviceable."""
    return NodeConfig(
        name="busy_in_time",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="busy_02b",
                    script_text="น้องใจ ขออนุญาตติดต่อใหม่ตามวัน ที่ลูกค้าแจ้งได้ นะคะ, สวัสดีค่ะ",
                    after_speaking="call wrap_up ทันที",
                ),
            )
        ],
        functions=[],
    )


def create_busy_out_time_node(state: dict | None = None) -> NodeConfig:
    """Close the busy flow when the requested callback time is outside working hours."""
    return NodeConfig(
        name="busy_out_time",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="busy_02c",
                    script_text=(
                        "เวลาลูกค้าแจ้งมา น้องใจ ไม่สามารถให้บริการตามเวลาที่แจ้งได้ "
                        "ขออนุญาตติดต่อใหม่ภายในเวลาทำการ นะคะ, สวัสดีค่ะ"
                    ),
                    after_speaking="call wrap_up ทันที",
                ),
            )
        ],
        functions=[],
    )


def create_other_person_node(state: dict | None = None) -> NodeConfig:
    """Handle third-party answering the call."""
    s = state or {}
    return NodeConfig(
        name="other_person",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="other_person_01",
                    script_text="ขออภัยคะ ขออนุญาตวางสาย",
                    after_speaking="call other_person_response พร้อม message_left=false ทันที",
                    state=s,
                ),
            )
        ],
        functions=[],
    )


def create_paid_node(state: dict | None = None) -> NodeConfig:
    """Acknowledge customer who has already paid."""
    return NodeConfig(
        name="paid",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="paid_01",
                    script_text=(
                        "น้องใจขอบคุณสำหรับการชำระเงินและใช้บริการบริษัทเงินให้ใจจำกัด "
                        "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ สวัสดีค่ะ"
                    ),
                    after_speaking="call wrap_up ทันที",
                ),
            )
        ],
        functions=[],
    )


def create_voicemail_node(state: dict | None = None) -> NodeConfig:
    """Leave a message on voicemail/answering machine."""
    s = state or {}
    return NodeConfig(
        name="voicemail",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="voicemail_01",
                    script_text="ขออนุญาตติดต่อใหม่ภายหลังนะคะ, สวัสดีค่ะ",
                    after_speaking="call wrap_up ทันที",
                    state=s,
                ),
            )
        ],
        functions=[],
    )


def create_thank_you_node(state: dict | None = None) -> NodeConfig:
    """Thank the customer and close after PTP is secured."""
    s = state or {}
    return NodeConfig(
        name="thank_you",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="thank_you_01",
                    script_text=(
                        "น้องใจขอบคุณที่ใช้บริการบริษัทเงินให้ใจจำกัด "
                        "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ สวัสดีค่ะ"
                    ),
                    after_speaking="call wrap_up ทันที",
                    state=s,
                ),
            )
        ],
        functions=[],
    )


def create_refused_node(state: dict | None = None) -> NodeConfig:
    """Close call politely after customer finally refuses."""
    return NodeConfig(
        name="refused",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="refused_01",
                    script_text=(
                        "หากลูกค้ายังไม่สะดวก ไม่เป็นไรค่ะ น้องใจขออนุญาตติดต่อหาลูกค้าอีกครั้งนะคะ "
                        "หากต้องการสอบถามข้อมูลเพิ่มเติมสามารถติดต่อได้ที่ 02 078 8899 ค่ะ "
                        "ขอบคุณที่ใช้บริการบริษัทเงินให้ใจจำกัด สวัสดีค่ะ"
                    ),
                    after_speaking="call wrap_up ทันที",
                ),
            )
        ],
        functions=[],
    )


def create_fallback_node(state: dict | None = None) -> NodeConfig:
    """Handle no-response or repeated misunderstandings."""
    return NodeConfig(
        name="fallback",
        task_messages=[
            _task_message(
                _verbatim_task_content(
                    script_id="fallback_01",
                    script_text="ขออภัยคะ น้องใจ จะแจ้งให้เจ้าหน้าที่ติดต่อกลับอีกครั้ง, สวัสดีค่ะ",
                    after_speaking="call wrap_up ทันที",
                ),
            )
        ],
        functions=[],
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
