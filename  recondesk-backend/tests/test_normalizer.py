"""Pytest tests for app/services/normalizer.py.

Pre-verified valid GSTINs used throughout (checksum computed manually):
  VALID_MH       = "27ABCDE1234F1Z1"  state=27, sum=215, ck=CHARSET[1]='1'
  VALID_KA       = "29ABCDE1234F1ZX"  state=29, sum=219, ck=CHARSET[33]='X'
  VALID_CHECK0   = "27ABCDE1234F2Z0"  state=27, sum=216, ck=CHARSET[0]='0'  (sum%36==0)
  VALID_CHECK9   = "23ABCDE1234F1Z9"  state=23, sum=207, ck=CHARSET[9]='9'
  VALID_07       = "07ABCDE1234F1Z3"  state=07, sum=213, ck=CHARSET[3]='3'
"""

import datetime
import pathlib
import pytest

from app.services.normalizer import (
    ALLOWED_NOTES,
    NormalizationError,
    NormalizationResult,
    batch_normalize_gstins,
    normalize_amount,
    normalize_date,
    normalize_gstin,
    normalize_invoice_number,
)

# ---------------------------------------------------------------------------
# Known-good fixtures
# ---------------------------------------------------------------------------
VALID_MH = "27ABCDE1234F1Z1"
VALID_KA = "29ABCDE1234F1ZX"
VALID_CHECK0 = "27ABCDE1234F2Z0"
VALID_CHECK9 = "23ABCDE1234F1Z9"
VALID_07 = "07ABCDE1234F1Z3"

ALL_VALID = [VALID_MH, VALID_KA, VALID_CHECK0, VALID_CHECK9, VALID_07]

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _raises_reason(raw, expected_reason: str) -> None:
    with pytest.raises(NormalizationError) as exc_info:
        normalize_gstin(raw)
    assert exc_info.value.reason == expected_reason


# ===========================================================================
# 1. Whitelist / silent cleaning tests (tests 1–9)
# ===========================================================================

def test_01_lowercase_converted():
    assert normalize_gstin("27abcde1234f1z1") == VALID_MH


def test_02_dashes_removed():
    assert normalize_gstin("27-ABCDE-1234-F1Z1") == VALID_MH


def test_03_spaces_removed():
    assert normalize_gstin("27 ABCDE 1234 F1Z1") == VALID_MH


def test_04_dots_removed():
    assert normalize_gstin("27.ABCDE.1234.F1Z1") == VALID_MH


def test_05_tab_removed():
    assert normalize_gstin("27\tABCDE1234F1Z1") == VALID_MH


def test_06_newline_removed():
    assert normalize_gstin("27\nABCDE1234F1Z1") == VALID_MH


def test_07_slash_removed():
    assert normalize_gstin("27/ABCDE/1234/F1Z1") == VALID_MH


def test_08_underscore_removed():
    assert normalize_gstin("27_ABCDE_1234_F1Z1") == VALID_MH


def test_09_invisible_unicode_removed():
    # U+200B zero-width space is not in [0-9A-Z] and is silently dropped.
    assert normalize_gstin("27\u200bABCDE1234F1Z1") == VALID_MH


# ===========================================================================
# 2. Semantic-empty after whitelist (test 10)
# ===========================================================================

def test_10_semantic_empty_after_whitelist():
    # After whitelist cleaning "@@@###$$$" becomes "" → reason "empty"
    _raises_reason("@@@###$$$", "empty")


# ===========================================================================
# 3. Devanagari / non-ASCII stripping leads to wrong length (test 11)
# ===========================================================================

def test_11_devanagari_digits_yield_invalid_length():
    # "२७ABCDE1234F1Z1": the two Devanagari codepoints (non-ASCII) are stripped,
    # leaving "ABCDE1234F1Z1" = 13 chars → reason "invalid_length"
    _raises_reason("२७ABCDE1234F1Z1", "invalid_length")


# ===========================================================================
# 4. Non-string type guards (tests 12–14)
# ===========================================================================

def test_12_int_input_raises_invalid_format():
    _raises_reason(123456789012345, "invalid_format")


def test_13_list_input_raises_invalid_format():
    _raises_reason(["27ABCDE1234F1Z5"], "invalid_format")


def test_14_dict_input_raises_invalid_format():
    _raises_reason({"gstin": "27ABCDE1234F1Z5"}, "invalid_format")


# ===========================================================================
# 5. Valid GSTINs (tests 15–16)
# ===========================================================================

def test_15_valid_maharashtra_gstin():
    assert normalize_gstin(VALID_MH) == VALID_MH


def test_16_valid_karnataka_gstin():
    assert normalize_gstin(VALID_KA) == VALID_KA


# ===========================================================================
# 6. Invalid checksum variants (tests 17–19)
# ===========================================================================

def test_17_invalid_checksum_variant_1():
    # VALID_MH with last char changed from '1' to '2'
    _raises_reason("27ABCDE1234F1Z2", "invalid_checksum")


def test_18_invalid_checksum_variant_2():
    # VALID_MH with last char changed from '1' to '3'
    _raises_reason("27ABCDE1234F1Z3", "invalid_checksum")


def test_19_invalid_checksum_variant_3():
    # VALID_CHECK0 with last char changed from '0' to '1'
    # (sum=216, expected='0', actual='1')
    _raises_reason("27ABCDE1234F2Z1", "invalid_checksum")


# ===========================================================================
# 7. Wrong length (tests 20–21)
# ===========================================================================

def test_20_wrong_length_14():
    _raises_reason("27ABCDE1234F1Z", "invalid_length")


def test_21_wrong_length_16():
    _raises_reason("27ABCDE1234F1Z1X", "invalid_length")


# ===========================================================================
# 8. Empty / None (tests 22–23)
# ===========================================================================

def test_22_empty_string():
    _raises_reason("", "empty")


def test_23_none_input():
    _raises_reason(None, "empty")


# ===========================================================================
# 9. Clean input that fails GSTIN_REGEX → invalid_format (test 24)
# ===========================================================================

def test_24_invalid_format_clean_input():
    # "27ABCDE1234FAZB": 15 chars, no dirty chars, but position 12 ('A') must
    # be [0-9] per the regex → fails GSTIN_REGEX → reason "invalid_format".
    _raises_reason("27ABCDE1234FAZB", "invalid_format")


# ===========================================================================
# 10. Idempotency: normalize(normalize(x)) == normalize(x) (tests 25–29)
# ===========================================================================

def test_25_idempotency_valid_mh():
    assert normalize_gstin(normalize_gstin(VALID_MH)) == normalize_gstin(VALID_MH)


def test_26_idempotency_valid_ka():
    assert normalize_gstin(normalize_gstin(VALID_KA)) == normalize_gstin(VALID_KA)


def test_27_idempotency_valid_check0():
    assert normalize_gstin(normalize_gstin(VALID_CHECK0)) == normalize_gstin(VALID_CHECK0)


def test_28_idempotency_valid_check9():
    assert normalize_gstin(normalize_gstin(VALID_CHECK9)) == normalize_gstin(VALID_CHECK9)


def test_29_idempotency_valid_07():
    assert normalize_gstin(normalize_gstin(VALID_07)) == normalize_gstin(VALID_07)


# ===========================================================================
# 11. Determinism: 100 calls produce identical result (test 30)
# ===========================================================================

def test_30_determinism_100_calls():
    first = normalize_gstin(VALID_MH)
    for _ in range(99):
        assert normalize_gstin(VALID_MH) == first


# ===========================================================================
# 12. No mutation of input (test 31)
# ===========================================================================

def test_31_no_mutation_of_input():
    raw = "27 ABCDE 1234 F1Z1"
    original = raw  # same object value
    normalize_gstin(raw)
    assert raw == original


# ===========================================================================
# 13. Checksum boundary: sum % 36 == 0 → checksum char '0' (test 32)
# ===========================================================================

def test_32_checksum_boundary_zero():
    # sum=216, 216 % 36 == 0, CHARSET[(36-0)%36] = CHARSET[0] = '0'
    assert normalize_gstin(VALID_CHECK0) == VALID_CHECK0
    assert VALID_CHECK0[-1] == "0"


# ===========================================================================
# 14. Checksum boundary: checksum char '9' (test 33)
# ===========================================================================

def test_33_checksum_boundary_nine():
    # sum=207, 207 % 36 == 27, CHARSET[(36-27)%36] = CHARSET[9] = '9'
    assert normalize_gstin(VALID_CHECK9) == VALID_CHECK9
    assert VALID_CHECK9[-1] == "9"


# ===========================================================================
# 15. Checksum correctness: manually verify expected digit (test 34)
# ===========================================================================

def test_34_checksum_correctness_manually_computed():
    # VALID_MH = "27ABCDE1234F1Z1"
    # CHARSET indices: 2,7,10,11,12,13,14,1,2,3,4,15,1,35
    # Factors:         1,2, 1, 2, 1, 2, 1,2,1,2,1, 2,1, 2
    # Products:        2,14,10,22,12,26,14,2,2,6,4,30,1,70  → sum=215
    # expected = CHARSET[(36 - 215%36) % 36] = CHARSET[(36-35)%36] = CHARSET[1] = '1'
    result = normalize_gstin(VALID_MH)
    assert result[-1] == "1"


# ===========================================================================
# 16. Alternating factor correctness: swapping adjacent PAN chars → invalid_checksum (test 35)
# ===========================================================================

def test_35_adjacent_swap_invalidates_checksum():
    # Swap positions 2 and 3 in VALID_MH: "27ABCDE1234F1Z1" → "27BACDE1234F1Z1"
    # New sum: 2+14+11+20+12+26+14+2+2+6+4+30+1+70=214 → expected='2', actual='1'
    _raises_reason("27BACDE1234F1Z1", "invalid_checksum")


# ===========================================================================
# 17. Factor direction: [1,2,...] not [2,1,...] (test 36)
# ===========================================================================

def test_36_alternating_factor_direction_starts_with_one():
    # "27ABCDE1234F1Z5" has checksum '5', which is correct under factors [2,1,...]:
    #   sum_reversed=175, 175%36=31, CHARSET[(36-31)%36]=CHARSET[5]='5'
    # Under the correct [1,2,...] factors sum=215, expected='1' ≠ '5' → invalid_checksum.
    _raises_reason("27ABCDE1234F1Z5", "invalid_checksum")


# ===========================================================================
# 18. Error consistency: same invalid input always raises same reason (test 37)
# ===========================================================================

def test_37_error_consistency_10_calls():
    for _ in range(10):
        _raises_reason("27ABCDE1234F1Z2", "invalid_checksum")


# ===========================================================================
# 19. "invalid_characters" reason is never present in source (test 38)
# ===========================================================================

def test_38_invalid_characters_reason_never_raised():
    source_path = (
        pathlib.Path(__file__).parent.parent / "app" / "services" / "normalizer.py"
    )
    source_text = source_path.read_text()
    assert "invalid_characters" not in source_text


# ===========================================================================
# 20. All four valid reason strings are each triggered at least once (test 39)
# ===========================================================================

def test_39_all_four_reason_types_triggered():
    reasons: set = set()

    for raw, reason in [
        ("", "empty"),
        ("SHORT", "invalid_length"),
        ("27ABCDE1234FAZB", "invalid_format"),
        ("27ABCDE1234F1Z2", "invalid_checksum"),
    ]:
        with pytest.raises(NormalizationError) as exc_info:
            normalize_gstin(raw)
        assert exc_info.value.reason == reason
        reasons.add(reason)

    assert reasons == {"empty", "invalid_length", "invalid_format", "invalid_checksum"}


# ===========================================================================
# 21. Batch: valid output preserves input order (test 40)
# ===========================================================================

def test_40_batch_valid_output_preserves_input_order():
    raw_list = [VALID_KA, VALID_MH, VALID_07]
    result = batch_normalize_gstins(raw_list)
    normalized_list = [item["normalized"] for item in result["valid"]]
    assert normalized_list == [VALID_KA, VALID_MH, VALID_07]


# ===========================================================================
# 22. Batch: invalid entries carry original list index (test 41)
# ===========================================================================

def test_41_batch_invalid_preserves_original_index():
    raw_list = [VALID_MH, "BAD", VALID_KA, "", "TOOSHORT"]
    result = batch_normalize_gstins(raw_list)
    invalid_indices = [item["index"] for item in result["invalid"]]
    # "BAD" is at index 1, "" at index 3, "TOOSHORT" at index 4
    assert invalid_indices == [1, 3, 4]


# ===========================================================================
# 23. Batch deduplication: GSTIN appearing 3× → once in duplicates (test 42)
# ===========================================================================

def test_42_batch_dedup_three_occurrences_listed_once():
    raw_list = [VALID_MH, VALID_MH, VALID_KA, VALID_MH]
    result = batch_normalize_gstins(raw_list)
    assert result["duplicates"].count(VALID_MH) == 1


# ===========================================================================
# 24. Batch duplicates preserve first-occurrence order (test 43)
# ===========================================================================

def test_43_batch_duplicates_preserve_first_occurrence_order():
    # VALID_KA appears first (index 0), VALID_MH appears second (index 1).
    # Both appear multiple times; duplicates must be in first-seen order.
    raw_list = [VALID_KA, VALID_MH, VALID_KA, VALID_MH]
    result = batch_normalize_gstins(raw_list)
    assert result["duplicates"] == [VALID_KA, VALID_MH]


# ===========================================================================
# 25. Batch duplicates sourced from valid only, not invalid (test 44)
# ===========================================================================

def test_44_batch_duplicates_from_valid_only():
    # "27ABCDE1234F1Z2" is invalid (bad checksum).  Even if it appears twice,
    # it must NOT appear in duplicates (which tracks normalized valid GSTINs).
    raw_list = ["27ABCDE1234F1Z2", "27ABCDE1234F1Z2", VALID_MH]
    result = batch_normalize_gstins(raw_list)
    assert len(result["invalid"]) == 2
    assert result["duplicates"] == []


# ===========================================================================
# 26. Batch stability: same input produces identical output twice (test 45)
# ===========================================================================

def test_45_batch_stability():
    raw_list = [VALID_MH, "BAD", VALID_KA, VALID_MH]
    assert batch_normalize_gstins(raw_list) == batch_normalize_gstins(raw_list)


# ===========================================================================
# 27. Batch no mutation: raw_list unchanged after batch call (test 46)
# ===========================================================================

def test_46_batch_no_mutation_of_raw_list():
    raw_list = [VALID_MH, "BAD", VALID_KA]
    snapshot = list(raw_list)
    batch_normalize_gstins(raw_list)
    assert raw_list == snapshot


# ===========================================================================
# 28. No global mutable state: two independent calls produce correct results (test 47)
# ===========================================================================

def test_47_no_global_mutable_state():
    result_mh = normalize_gstin(VALID_MH)
    result_ka = normalize_gstin(VALID_KA)
    # Each call must still return the correct value, unaffected by the other.
    assert result_mh == VALID_MH
    assert result_ka == VALID_KA


# ===========================================================================
# normalize_date — tests 48–62
# ===========================================================================

def test_48_date_dd_mm_yyyy_dash():
    r = normalize_date("08-04-2024")
    assert r.value == datetime.date(2024, 4, 8)
    assert r.notes == []


def test_49_date_dd_mm_yyyy_slash():
    r = normalize_date("08/04/2024")
    assert r.value == datetime.date(2024, 4, 8)
    assert r.notes == []


def test_50_date_dd_mm_yyyy_dot():
    r = normalize_date("08.04.2024")
    assert r.value == datetime.date(2024, 4, 8)
    assert r.notes == []


def test_51_date_yyyy_mm_dd_iso():
    r = normalize_date("2024-04-08")
    assert r.value == datetime.date(2024, 4, 8)
    assert r.notes == []


def test_52_date_two_digit_year_2024():
    # yy=24 ≤ 69 → 2024
    r = normalize_date("08-04-24")
    assert r.value == datetime.date(2024, 4, 8)
    assert "two_digit_year_expanded" in r.notes


def test_53_date_two_digit_year_1999():
    # yy=99 ≥ 70 → 1999
    r = normalize_date("31/12/99")
    assert r.value == datetime.date(1999, 12, 31)
    assert "two_digit_year_expanded" in r.notes


def test_54_date_ambiguous_01_02_03_always_dd_mm_yy():
    # "01-02-03" must be treated as day=1, month=2, yy=3 → 2003
    r = normalize_date("01-02-03")
    assert r.value == datetime.date(2003, 2, 1)
    assert "two_digit_year_expanded" in r.notes


def test_55_date_month_name_space_separator():
    r = normalize_date("08 APR 2024")
    assert r.value == datetime.date(2024, 4, 8)
    assert r.notes == []


def test_56_date_month_name_dash_separator():
    r = normalize_date("08-Apr-2024")
    assert r.value == datetime.date(2024, 4, 8)
    assert r.notes == []


def test_57_date_month_name_two_digit_year():
    r = normalize_date("08-apr-24")
    assert r.value == datetime.date(2024, 4, 8)
    assert "two_digit_year_expanded" in r.notes


def test_58_date_month_name_lowercase_full():
    r = normalize_date("01 april 2024")
    assert r.value == datetime.date(2024, 4, 1)
    assert r.notes == []


def test_59_date_excel_serial_float():
    # Independent verification — no implementation formula used:
    #   Known anchor: Excel serial 36526 = 2000-01-01 (universally documented).
    #   2000-01-01 → 2024-01-01: 24 years, 6 leap (2000,04,08,12,16,20) → 8 766 days
    #                             → serial 36526 + 8766 = 45292 = 2024-01-01
    #   2024-01-01 → 2024-04-08: 31(Jan remaining) + 29(Feb leap) + 31(Mar) + 8(Apr)
    #                             = 98 more days → serial 45292 + 98 = 45390 = 2024-04-08 ✓
    r = normalize_date(45390.0)
    assert r.value == datetime.date(2024, 4, 8)
    assert "excel_serial_converted" in r.notes


def test_60_date_excel_serial_numeric_string():
    # Same independently verified anchor as test_59: 45390 = 2024-04-08.
    # Also tests the float-string variant ("45390.0") in the same breath.
    r = normalize_date("45390")
    assert r.value == datetime.date(2024, 4, 8)
    assert "excel_serial_converted" in r.notes

    r2 = normalize_date("45390.0")
    assert r2.value == datetime.date(2024, 4, 8)
    assert "excel_serial_converted" in r2.notes


def test_61_date_excel_datetime_string_strips_time():
    r = normalize_date("2024-04-08 00:00:00")
    assert r.value == datetime.date(2024, 4, 8)
    assert "time_stripped" in r.notes
    assert "excel_serial_converted" not in r.notes


def test_62_date_invalid_date_raises_error():
    with pytest.raises(NormalizationError) as exc_info:
        normalize_date("31-02-2024")
    assert exc_info.value.reason == "invalid_date"
    assert exc_info.value.field == "date"


def test_63_date_invalid_format_raises_error():
    with pytest.raises(NormalizationError) as exc_info:
        normalize_date("garbage")
    assert exc_info.value.reason == "invalid_format"


# ===========================================================================
# normalize_amount — tests 63–77  (file sequence: 64–78)
# ===========================================================================

def test_64_amount_plain_integer_string():
    r = normalize_amount("1000")
    assert r.value == 100_000
    assert r.notes == []


def test_65_amount_rupee_symbol_and_commas():
    r = normalize_amount("₹1,000")
    assert r.value == 100_000
    assert r.notes == ["symbols_stripped", "commas_stripped"]


def test_66_amount_excel_apostrophe_prefix():
    r = normalize_amount("'45000")
    assert r.value == 4_500_000
    assert r.notes == ["symbols_stripped"]


def test_67_amount_decimal_lakh_suffix():
    # 12.5L = 12,50,000 rupees = 1,25,00,000 paise (western: 125_000_000)
    r = normalize_amount("12.5L")
    assert r.value == 125_000_000
    assert r.notes == ["lakh_suffix_converted"]


def test_68_amount_rupee_parentheses_negative():
    # ₹(1,000.50) → −100050 paise
    r = normalize_amount("₹(1,000.50)")
    assert r.value == -100_050
    assert r.notes == ["symbols_stripped", "commas_stripped", "parentheses_negative"]


def test_69_amount_crore_suffix():
    # 2Cr = 2,00,00,000 rupees = 2,00,00,00,000 paise
    r = normalize_amount("2Cr")
    assert r.value == 2_000_000_000
    assert r.notes == ["crore_suffix_converted"]


def test_70_amount_minus_prefix_negative():
    r = normalize_amount("-1000")
    assert r.value == -100_000
    assert r.notes == []


def test_71_amount_parentheses_negative_no_symbol():
    r = normalize_amount("(1000)")
    assert r.value == -100_000
    assert r.notes == ["parentheses_negative"]


def test_72_amount_dot_zero_zero_suffix():
    r = normalize_amount("1000.00")
    assert r.value == 100_000
    assert r.notes == []


def test_73_amount_k_suffix():
    r = normalize_amount("10K")
    assert r.value == 1_000_000
    assert r.notes == ["k_suffix_converted"]


def test_74_amount_lakh_lowercase_suffix():
    r = normalize_amount("5lakh")
    assert r.value == 50_000_000
    assert r.notes == ["lakh_suffix_converted"]


def test_75_amount_internal_spaces_stripped():
    # "1 2 3 4" → 1234 rupees → 123400 paise
    r = normalize_amount("1 2 3 4")
    assert r.value == 123_400
    assert r.notes == ["internal_spaces_stripped"]


def test_76_amount_multiple_suffixes_raises_error():
    with pytest.raises(NormalizationError) as exc_info:
        normalize_amount("12LakhCr")
    assert exc_info.value.reason == "multiple_suffixes"


def test_77_amount_overflow_raises_error():
    # 1000Cr = 1000 × 1,00,00,000 rupees × 100 = 10^12 paise → overflow
    with pytest.raises(NormalizationError) as exc_info:
        normalize_amount("1000Cr")
    assert exc_info.value.reason == "overflow"


def test_78_amount_unparseable_raises_invalid_format():
    with pytest.raises(NormalizationError) as exc_info:
        normalize_amount("@@@")
    assert exc_info.value.reason == "invalid_format"


# ===========================================================================
# normalize_invoice_number — tests 79–93
# ===========================================================================

def test_79_invoice_strips_dash():
    r = normalize_invoice_number("INV-001")
    assert r.value == "INV001"
    assert r.notes == ["symbols_stripped"]


def test_80_invoice_pure_numeric_strips_leading_zeros():
    r = normalize_invoice_number("000123")
    assert r.value == "123"
    assert "leading_zeros_stripped" in r.notes


def test_81_invoice_already_normalized_no_notes():
    r = normalize_invoice_number("INV001")
    assert r.value == "INV001"
    assert r.notes == []


def test_82_invoice_lowercase_slash():
    r = normalize_invoice_number("inv/001")
    assert r.value == "INV001"
    assert "symbols_stripped" in r.notes
    assert "uppercased" in r.notes


def test_83_invoice_hash_space_dot_stripped():
    r = normalize_invoice_number("#INV 2024.001")
    assert r.value == "INV2024001"
    assert "symbols_stripped" in r.notes


def test_84_invoice_at_signs_raises_empty_after_normalization():
    with pytest.raises(NormalizationError) as exc_info:
        normalize_invoice_number("@@@")
    assert exc_info.value.reason == "empty_after_normalization"


def test_85_invoice_all_zeros_raises_empty_after_normalization():
    # "000000" → purely numeric → strip leading zeros → "" → error
    with pytest.raises(NormalizationError) as exc_info:
        normalize_invoice_number("000000")
    assert exc_info.value.reason == "empty_after_normalization"


def test_86_invoice_lowercase_truncated_and_uppercased():
    # 60 lowercase 'a' chars → stripped to "" ... no: 'a' is alphanumeric
    # 60 'a' → upper → 60 'A' → truncate to 50
    r = normalize_invoice_number("a" * 60)
    assert r.value == "A" * 50
    assert "uppercased" in r.notes
    assert "truncated_to_50_chars" in r.notes


def test_87_invoice_parentheses_stripped():
    r = normalize_invoice_number("INV(001)")
    assert r.value == "INV001"
    assert "symbols_stripped" in r.notes


def test_88_invoice_spaces_stripped():
    r = normalize_invoice_number("  INV-001  ")
    assert r.value == "INV001"
    assert "symbols_stripped" in r.notes


def test_89_invoice_lowercase_alphanumeric():
    r = normalize_invoice_number("abc-123")
    assert r.value == "ABC123"
    assert "symbols_stripped" in r.notes
    assert "uppercased" in r.notes


def test_90_invoice_dot_slash_stripped():
    r = normalize_invoice_number("INV.2024/001")
    assert r.value == "INV2024001"
    assert "symbols_stripped" in r.notes


def test_91_invoice_alphanumeric_preserves_leading_zeros():
    # "001abc" → strip nothing → upper → "001ABC" (not purely numeric → no zero strip)
    r = normalize_invoice_number("001abc")
    assert r.value == "001ABC"
    assert "uppercased" in r.notes
    assert "leading_zeros_stripped" not in r.notes


def test_92_invoice_already_uppercase_no_uppercase_note():
    r = normalize_invoice_number("001ABC")
    assert r.value == "001ABC"
    assert "uppercased" not in r.notes


def test_93_invoice_long_alphanumeric_truncated():
    # "INV" + "0" * 50 → 53 chars, not purely numeric → truncate to 50
    raw = "INV" + "0" * 50
    r = normalize_invoice_number(raw)
    assert len(r.value) == 50
    assert r.value == "INV" + "0" * 47
    assert "truncated_to_50_chars" in r.notes
    assert "leading_zeros_stripped" not in r.notes
