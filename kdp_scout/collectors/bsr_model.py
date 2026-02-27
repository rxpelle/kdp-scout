"""BSR (Best Sellers Rank) to sales estimation model.

Phase 2 Implementation:
- Convert Amazon BSR numbers to estimated daily/monthly sales
- Use calibrated power-law model based on known data points
- Support different category-specific models
- Calculate estimated monthly revenue from sales + price
- Track BSR changes over time to detect trends
- Provide confidence intervals for estimates

The core model follows: daily_sales = A * BSR^(-B)
Where A and B are calibrated constants for each store/category.
For Amazon US Kindle Store, typical values are:
  A ~ 100,000, B ~ 0.75

Reference calibration points:
  BSR 1 = ~1,000 sales/day
  BSR 100 = ~100 sales/day
  BSR 1,000 = ~25 sales/day
  BSR 10,000 = ~5 sales/day
  BSR 100,000 = ~0.5 sales/day
  BSR 500,000 = ~0.1 sales/day
"""


def estimate_daily_sales(bsr, category='kindle_store'):
    """Estimate daily sales from a BSR number.

    Phase 2: Will use a calibrated power-law model to estimate
    daily unit sales from Best Sellers Rank.

    Args:
        bsr: Best Sellers Rank number.
        category: Category for model selection.

    Returns:
        Estimated daily sales as a float.
    """
    raise NotImplementedError('BSR model will be implemented in Phase 2')


def estimate_monthly_revenue(bsr, price, category='kindle_store'):
    """Estimate monthly revenue from BSR and price.

    Phase 2: Will combine daily sales estimate with price to
    calculate projected monthly revenue.

    Args:
        bsr: Best Sellers Rank number.
        price: Book price in dollars.
        category: Category for model selection.

    Returns:
        Estimated monthly revenue as a float.
    """
    raise NotImplementedError('BSR model will be implemented in Phase 2')
