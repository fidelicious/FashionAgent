"""
Clawbot's Discord interface.

This package wraps discord.py. It is imported lazily (only when
``config.discord.enabled`` is true) so foundation tests don't pay the
import cost.

Layout
------
bot.py         : BotContext, build_bot(), the global whitelist check.
cogs/health.py : /health (Step 6)
cogs/profile.py: /profile, /profile set (Step 6)
cogs/wardrobe.py: /wardrobe (Step 6)
cogs/items.py  : /add_item, /edit_item, /forget_item (Step 7)

Naming note
-----------
This sub-package shares its name with the third-party ``discord`` package
from discord.py. Python 3's absolute-import default makes ``import discord``
inside this directory resolve to the third-party library, not back to here —
do *not* introduce ``from . import discord`` shortcuts.
"""

from clawbot.discord.bot import BotContext, build_bot, is_whitelisted

__all__ = ["BotContext", "build_bot", "is_whitelisted"]
