"""Tests for workers.discount_verification.

Uses ``respx`` to mock httpx responses. Seeds retailers + a single
``DiscountProgram`` row per test and asserts the summary dict +
post-run row state.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from sqlalchemy import text

from app.core_models import Retailer
from modules.m5_identity.models import DiscountProgram
from workers.discount_verification import run_discount_verification

TEST_URL = "https://example.com/discount-program"
PROGRAM_NAME = "Veteran Appreciation"


async def _seed_retailer(db, retailer_id: str) -> None:
    if (
        await db.execute(
            text("SELECT 1 FROM retailers WHERE id = :id"), {"id": retailer_id}
        )
    ).scalar_one_or_none() is None:
        db.add(
            Retailer(
                id=retailer_id,
                display_name=retailer_id.replace("_", " ").title(),
                base_url=f"https://www.{retailer_id}.com",
                extraction_method="agent_browser",
                supports_identity=True,
            )
        )
        await db.flush()


async def _seed_program(
    db,
    retailer_id: str,
    *,
    last_verified: datetime | None = None,
    consecutive_failures: int = 0,
    is_active: bool = True,
) -> DiscountProgram:
    program = DiscountProgram(
        retailer_id=retailer_id,
        program_name=PROGRAM_NAME,
        program_type="identity",
        eligibility_type="veteran",
        discount_type="percentage",
        discount_value=Decimal("10"),
        verification_method="id_me",
        verification_url=TEST_URL,
        url=TEST_URL,
        is_active=is_active,
        last_verified=last_verified,
        consecutive_failures=consecutive_failures,
    )
    db.add(program)
    await db.flush()
    return program


@pytest.mark.asyncio
async def test_verify_active_program_updates_last_verified(db_session):
    await _seed_retailer(db_session, "amazon")
    program = await _seed_program(db_session, "amazon")

    with respx.mock(assert_all_called=False) as mock:
        mock.get(TEST_URL).respond(
            200,
            text=f"<html><body>Welcome to {PROGRAM_NAME}</body></html>",
        )
        summary = await run_discount_verification(
            db_session, stale_days=1, failure_threshold=3
        )

    assert summary["checked"] == 1
    assert summary["verified"] == 1
    assert summary["failed"] == 0
    assert summary["flagged"] == 0
    assert summary["deactivated"] == 0
    assert program.last_verified is not None
    assert program.consecutive_failures == 0
    assert program.is_active is True


@pytest.mark.asyncio
async def test_verify_flagged_missing_mention_does_not_increment_failures(
    db_session,
):
    await _seed_retailer(db_session, "amazon")
    program = await _seed_program(db_session, "amazon")

    with respx.mock(assert_all_called=False) as mock:
        mock.get(TEST_URL).respond(
            200, text="<html><body>Unrelated content</body></html>"
        )
        summary = await run_discount_verification(
            db_session, stale_days=1, failure_threshold=3
        )

    assert summary["checked"] == 1
    assert summary["verified"] == 0
    assert summary["flagged"] == 1
    assert summary["failed"] == 0
    assert summary["deactivated"] == 0
    assert program.consecutive_failures == 0
    assert program.is_active is True
    assert program.last_verified is not None


@pytest.mark.asyncio
async def test_verify_404_increments_failure_counter(db_session):
    await _seed_retailer(db_session, "amazon")
    program = await _seed_program(db_session, "amazon")

    with respx.mock(assert_all_called=False) as mock:
        mock.get(TEST_URL).respond(404, text="Not Found")
        summary = await run_discount_verification(
            db_session, stale_days=1, failure_threshold=3
        )

    assert summary["failed"] == 1
    assert summary["deactivated"] == 0
    assert program.consecutive_failures == 1
    assert program.is_active is True


@pytest.mark.asyncio
async def test_verify_network_error_increments_failure_counter(db_session):
    await _seed_retailer(db_session, "amazon")
    program = await _seed_program(db_session, "amazon")

    with respx.mock(assert_all_called=False) as mock:
        mock.get(TEST_URL).mock(side_effect=httpx.ConnectError("boom"))
        summary = await run_discount_verification(
            db_session, stale_days=1, failure_threshold=3
        )

    assert summary["failed"] == 1
    assert program.consecutive_failures == 1
    assert program.is_active is True


@pytest.mark.asyncio
async def test_three_consecutive_failures_deactivates_program(db_session):
    await _seed_retailer(db_session, "amazon")
    program = await _seed_program(
        db_session, "amazon", consecutive_failures=2
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get(TEST_URL).respond(500, text="Server Error")
        summary = await run_discount_verification(
            db_session, stale_days=1, failure_threshold=3
        )

    assert summary["failed"] == 1
    assert summary["deactivated"] == 1
    assert program.consecutive_failures == 3
    assert program.is_active is False


@pytest.mark.asyncio
async def test_successful_verification_resets_failure_counter(db_session):
    await _seed_retailer(db_session, "amazon")
    program = await _seed_program(
        db_session, "amazon", consecutive_failures=2
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.get(TEST_URL).respond(
            200,
            text=f"<html><body>Join the {PROGRAM_NAME} discount</body></html>",
        )
        summary = await run_discount_verification(
            db_session, stale_days=1, failure_threshold=3
        )

    assert summary["verified"] == 1
    assert program.consecutive_failures == 0
    assert program.is_active is True


@pytest.mark.asyncio
async def test_skips_programs_without_verification_url(db_session):
    await _seed_retailer(db_session, "amazon")
    program = DiscountProgram(
        retailer_id="amazon",
        program_name="No URL Program",
        program_type="identity",
        eligibility_type="student",
        discount_type="percentage",
        discount_value=Decimal("5"),
        verification_url=None,
        is_active=True,
        last_verified=datetime.now(UTC) - timedelta(days=30),
    )
    db_session.add(program)
    await db_session.flush()

    summary = await run_discount_verification(
        db_session, stale_days=1, failure_threshold=3
    )
    assert summary["checked"] == 0
