from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")

def money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)

def split_gst(taxable_value, rate, supplier_state_code, place_of_supply_code):
    taxable = money(taxable_value)
    rate = Decimal(str(rate))
    if not rate.is_finite() or rate < 0 or rate > 100:
        raise ValueError("GST rate must be between 0 and 100.")
    total = money(taxable * rate / Decimal("100"))
    if supplier_state_code and place_of_supply_code and str(supplier_state_code) == str(place_of_supply_code):
        half = money(total / Decimal("2"))
        return {"taxable_value": taxable, "gst_rate": rate, "cgst": half, "sgst": total-half, "igst": Decimal("0.00"), "tax_total": total, "tax_type": "intra_state"}
    return {"taxable_value": taxable, "gst_rate": rate, "cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": total, "tax_total": total, "tax_type": "inter_state"}
