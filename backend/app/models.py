"""Model registry — import all models so Alembic can discover them via Base.metadata."""

from app.database import Base  # noqa: F401
from app.core_models import (  # noqa: F401
    PredictionCache,
    Retailer,
    RetailerHealth,
    User,
    WatchdogEvent,
)
from modules.m1_product.models import Product  # noqa: F401
from modules.m2_prices.fb_location_models import FbMarketplaceLocation  # noqa: F401
from modules.m2_prices.models import Price, PriceHistory  # noqa: F401
from modules.m3_secondary.models import Listing  # noqa: F401
from modules.m4_coupons.models import CouponCache  # noqa: F401
from modules.m5_identity.models import (  # noqa: F401
    CardRewardProgram,
    DiscountProgram,
    PortalBonus,
    RotatingCategory,
    UserCard,
    UserCategorySelection,
    UserDiscountProfile,
)
from modules.m9_notify.models import WatchedItem  # noqa: F401
from modules.m10_savings.models import Receipt, ReceiptItem  # noqa: F401
from modules.m12_affiliate.models import AffiliateClick  # noqa: F401
from modules.m13_portal.models import PortalConfig  # noqa: F401
