from decimal import Decimal
from gst_calculations import split_gst

def test_intrastate_splits_equally():
    result = split_gst("100.00", "18", "01", "01")
    assert result["cgst"] == Decimal("9.00")
    assert result["sgst"] == Decimal("9.00")
    assert result["igst"] == Decimal("0.00")

def test_interstate_uses_igst():
    result = split_gst("100.00", "18", "01", "07")
    assert result["igst"] == Decimal("18.00")
    assert result["cgst"] == Decimal("0.00")
    assert result["sgst"] == Decimal("0.00")

def test_rounding_and_zero_rate():
    result = split_gst("10.01", "0", "01", "01")
    assert result["tax_total"] == Decimal("0.00")
