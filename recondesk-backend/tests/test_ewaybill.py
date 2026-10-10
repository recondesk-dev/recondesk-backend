"""Unit tests for E-Way Bill Service (NIC Schema V1.03/V1.04)."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from app.models.ewaybill import (
    CancelEwayBillInput,
    DocumentType,
    EwayBillCreateInput,
    EwayBillItemInput,
    EwayBillStatus,
    SubSupplyType,
    SupplyType,
    TransportMode,
    UpdateVehicleInput,
    VehicleType,
)
from app.services.billing.ewaybill_service import (
    build_nic_bulk_json,
    calculate_validity_period,
    cancel_ewaybill,
    create_standalone_ewaybill,
    generate_ewb_number,
    update_vehicle_details,
)


def test_calculate_validity_period_regular_cargo():
    now_dt = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)

    # 100 km -> 1 day
    v1 = calculate_validity_period(100, VehicleType.REGULAR, now_dt)
    assert (v1.date() - now_dt.date()).days == 1

    # 250 km -> 2 days (ceil(250/200))
    v2 = calculate_validity_period(250, VehicleType.REGULAR, now_dt)
    assert (v2.date() - now_dt.date()).days == 2

    # 550 km -> 3 days (ceil(550/200))
    v3 = calculate_validity_period(550, VehicleType.REGULAR, now_dt)
    assert (v3.date() - now_dt.date()).days == 3


def test_calculate_validity_period_over_dimensional_cargo():
    now_dt = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)

    # 50 km ODC -> 3 days (ceil(50/20))
    v = calculate_validity_period(50, VehicleType.OVER_DIMENSIONAL_CARGO, now_dt)
    assert (v.date() - now_dt.date()).days == 3


def test_generate_ewb_number():
    ewb = generate_ewb_number("27")
    assert len(ewb) == 12
    assert ewb.startswith("27")
    assert ewb.isdigit()

    ewb_dl = generate_ewb_number("07")
    assert len(ewb_dl) == 12
    assert ewb_dl.startswith("07")


def test_create_standalone_ewaybill():
    mock_sb = MagicMock()
    # Mock insert response
    mock_sb.table().insert().execute.return_value.data = [
        {"id": "11111111-1111-1111-1111-111111111111", "ewb_number": "271234567890", "status": "ACTIVE"}
    ]
    # Mock table check
    mock_sb.table().select().limit().execute.return_value.data = [{"id": "test"}]

    input_data = EwayBillCreateInput(
        client_gstin_id="22222222-2222-2222-2222-222222222222",
        supply_type=SupplyType.OUTWARD,
        sub_supply_type=SubSupplyType.SUPPLY,
        doc_type=DocumentType.TAX_INVOICE,
        doc_number="INV/2026/001",
        doc_date=date(2026, 10, 10),
        from_gstin="27AABCR1234F1Z5",
        from_trade_name="Supplier Private Limited",
        from_addr1="101 Business Hub",
        from_place="Mumbai",
        from_pincode=400001,
        from_state_code="27",
        to_gstin="29XYZAB1234F1Z1",
        to_trade_name="Buyer Enterprise",
        to_addr1="404 Tech Park",
        to_place="Bengaluru",
        to_pincode=560001,
        to_state_code="29",
        total_taxable_value=100000.0,
        cgst_amount=0.0,
        sgst_amount=0.0,
        igst_amount=18000.0,
        cess_amount=0.0,
        total_invoice_value=118000.0,
        items=[
            EwayBillItemInput(
                item_name="Industrial Motors",
                hsn_code="8501",
                quantity=10,
                unit="NOS",
                taxable_value=100000.0,
                igst_rate=18.0,
                igst_amount=18000.0,
            )
        ],
        transporter_id="27TRANS1234F1Z0",
        transporter_name="Fast Logistics",
        trans_mode=TransportMode.ROAD,
        distance_km=980,
        vehicle_no="MH12AB1234",
        vehicle_type=VehicleType.REGULAR,
    )

    res = create_standalone_ewaybill(mock_sb, input_data, user_id="user-123")
    assert res["status"] == "ACTIVE"
    assert res["ewb_number"] == "271234567890"


def test_update_vehicle_details():
    mock_sb = MagicMock()
    mock_sb.table().select().eq().execute.return_value.data = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "ewb_number": "271234567890",
            "status": "ACTIVE",
            "vehicle_no": "MH12AB1234",
            "vehicle_history": [],
        }
    ]
    mock_sb.table().update().eq().execute.return_value.data = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "vehicle_no": "MH14XY9999",
            "status": "ACTIVE",
        }
    ]

    upd = UpdateVehicleInput(
        ewb_number="271234567890",
        vehicle_no="MH14XY9999",
        from_place="Pune",
        from_state_code="27",
        reason_code="2",
        reason_remark="Transshipment at Pune Hub",
        trans_mode=TransportMode.ROAD,
    )

    res = update_vehicle_details(mock_sb, "11111111-1111-1111-1111-111111111111", upd, user_id="user-123")
    assert res["vehicle_no"] == "MH14XY9999"


def test_cancel_ewaybill_within_24h():
    mock_sb = MagicMock()
    # Generated 2 hours ago
    ewb_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    mock_sb.table().select().eq().execute.return_value.data = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "ewb_number": "271234567890",
            "ewb_date": ewb_time,
            "status": "ACTIVE",
        }
    ]
    mock_sb.table().update().eq().execute.return_value.data = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "status": "CANCELLED",
        }
    ]

    cancel_in = CancelEwayBillInput(
        ewb_number="271234567890",
        cancel_reason_code="2",
        cancel_remarks="Customer cancelled consignment",
    )

    res = cancel_ewaybill(mock_sb, "11111111-1111-1111-1111-111111111111", cancel_in, user_id="user-123")
    assert res["status"] == "CANCELLED"


def test_build_nic_bulk_json():
    records = [
        {
            "from_gstin": "27AABCR1234F1Z5",
            "from_trade_name": "Supplier Co",
            "from_addr1": "Plot 12",
            "from_place": "Mumbai",
            "from_pincode": 400001,
            "from_state_code": "27",
            "to_gstin": "29XYZAB1234F1Z1",
            "to_trade_name": "Buyer Co",
            "to_addr1": "Sector 4",
            "to_place": "Bengaluru",
            "to_pincode": 560001,
            "to_state_code": "29",
            "doc_number": "INV/001",
            "doc_date": "2026-10-10",
            "total_taxable_value": 50000.0,
            "igst_amount": 9000.0,
            "total_invoice_value": 59000.0,
            "distance_km": 980,
            "vehicle_no": "MH12AB1234",
            "items": [
                {
                    "item_name": "Sensors",
                    "hsn_code": "9031",
                    "quantity": 5,
                    "unit": "NOS",
                    "taxable_value": 50000.0,
                    "igst_rate": 18.0,
                }
            ],
        }
    ]

    payload = build_nic_bulk_json(records)
    assert payload["version"] == "1.0.1124"
    assert len(payload["billLists"]) == 1

    bill = payload["billLists"][0]
    assert bill["userGstin"] == "27AABCR1234F1Z5"
    assert bill["docNo"] == "INV/001"
    assert bill["vehicleNo"] == "MH12AB1234"
    assert bill["totInvValue"] == 59000.0
    assert len(bill["itemList"]) == 1
    assert bill["itemList"][0]["hsnCode"] == 9031
