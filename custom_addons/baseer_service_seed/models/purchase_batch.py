"""Legacy module hook retained for upgrade compatibility.

The former service-category override wrote a presentation-only
``purchase/expense`` value to batch rows.  Classification now comes from the
native product/account and analytic distribution, so no value is assigned.
"""
