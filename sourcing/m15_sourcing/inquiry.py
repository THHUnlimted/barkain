"""Distributor inquiry email drafts.

Pure module, no LLM. Per ``docs/FEATURES.md``'s classification rule this is
Traditional: it's a mail-merge over data we already have, and a template
produces a better business email than a language model here — buyers send these
by the dozen and want them identical, boring, and accurate.

The generated draft is deliberately short. A first-contact email to a
distributor is a qualification signal, not a pitch: it needs to establish that
you're a real reseller, name the specific item, state a quantity you'll actually
commit to, and ask one question. Anything longer reads like a form letter and
gets filtered.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SellerProfile:
    """The reseller's own details, merged into every draft."""

    business_name: str
    contact_name: str = ""
    email: str = ""
    phone: str = ""
    state: str = ""
    resale_certificate_state: str = ""
    marketplaces: tuple[str, ...] = ("Walmart Marketplace", "eBay")
    years_in_business: int | None = None
    ein_on_file: bool = True


@dataclass(frozen=True)
class InquiryDraft:
    subject: str
    body: str
    to: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"to": self.to, "subject": self.subject, "body": self.body}


def _quantity_phrase(case_pack: int | None, moq: int | None) -> str:
    """Describe the opening commitment in the distributor's own units."""
    if moq and case_pack and moq >= case_pack:
        cases = moq // case_pack
        unit = "case" if cases == 1 else "cases"
        return f"{moq} units ({cases} {unit} of {case_pack})"
    if moq:
        return f"{moq} units"
    if case_pack:
        return f"one case of {case_pack} units"
    return "an opening order"


def build_inquiry(
    *,
    seller: SellerProfile,
    product_name: str,
    brand: str | None = None,
    upc: str | None = None,
    sku: str | None = None,
    case_pack: int | None = None,
    moq: int | None = None,
    quoted_unit_cost: Decimal | None = None,
    distributor_name: str | None = None,
    distributor_email: str | None = None,
) -> InquiryDraft:
    """Compose a first-contact inquiry for one candidate item."""
    subject_brand = f"{brand} " if brand else ""
    subject = f"Wholesale inquiry — {subject_brand}{product_name}".strip()
    if len(subject) > 120:
        subject = subject[:117].rstrip() + "..."

    greeting = f"Hi {distributor_name}," if distributor_name else "Hello,"

    identifiers = []
    if brand:
        identifiers.append(f"Brand: {brand}")
    if upc:
        identifiers.append(f"UPC: {upc}")
    if sku:
        identifiers.append(f"SKU: {sku}")
    identifier_block = "\n".join(f"  {line}" for line in identifiers)

    marketplaces = (
        " and ".join(seller.marketplaces) if seller.marketplaces else "online marketplaces"
    )
    tenure = (
        f" We've been selling for {seller.years_in_business} years."
        if seller.years_in_business
        else ""
    )

    cost_line = ""
    if quoted_unit_cost is not None:
        # Naming the price you've seen is a deliberate choice: it tells a real
        # distributor you're already in the channel and shortcuts the
        # "send me your price list" round-trip. It also invites a better number.
        cost_line = (
            f"\nI've seen this quoted around ${quoted_unit_cost:.2f}/unit — "
            "if you can do better at volume I'd like to hear it.\n"
        )

    paperwork = []
    if seller.resale_certificate_state:
        paperwork.append(f"a {seller.resale_certificate_state} resale certificate")
    if seller.ein_on_file:
        paperwork.append("EIN")
    paperwork_line = (
        f"I can provide {' and '.join(paperwork)} on request."
        if paperwork
        else "I can provide reseller documentation on request."
    )

    signature_lines = [seller.contact_name, seller.business_name, seller.email, seller.phone]
    signature = "\n".join(line for line in signature_lines if line)

    body = f"""{greeting}

I'm a reseller at {seller.business_name} sourcing for {marketplaces}.{tenure}

I'd like to open an account and get pricing on:

  {product_name}
{identifier_block}

To start I'd be looking at {_quantity_phrase(case_pack, moq)}, with regular
reorders if it moves.
{cost_line}
{paperwork_line}

Could you let me know whether you're taking on new accounts for this line, and
what your terms and minimums look like?

Thanks,
{signature}
"""

    # Collapse the blank lines the optional blocks leave behind so the draft
    # doesn't arrive looking like a template that half-rendered.
    while "\n\n\n" in body:
        body = body.replace("\n\n\n", "\n\n")

    return InquiryDraft(subject=subject, body=body.strip() + "\n", to=distributor_email)
