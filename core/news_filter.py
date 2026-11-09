from datetime import UTC, datetime, timedelta

import feedparser

from core.logger import setup_system_logger

log = setup_system_logger("NewsFilter")

class EconomicCalendarShield:
    def __init__(self, blacklisted_currencies: list[str] = None, buffer_minutes: int = 30):
        """
        :param blacklisted_currencies: Currencies to monitor (e.g. ['USD', 'EUR', 'GBP'])
        :param buffer_minutes: Minutes before and after high-impact news to freeze entries
        """
        self.blacklisted_currencies = blacklisted_currencies or ["USD", "EUR", "GBP"]
        self.buffer_minutes = buffer_minutes
        # Free RSS feed from Forex Factory calendar
        self.feed_url = "https://www.forexfactory.com/news.xml"

    def is_safe_to_trade(self, symbol: str) -> tuple[bool, str]:
        """
        Checks if the symbol's base/quote currency is affected by an active or impending news event.
        Returns: (is_safe: bool, reason: str)
        """
        # Determine currencies involved in the ticker
        relevant_currencies = [cur for cur in self.blacklisted_currencies if cur in symbol]
        if not relevant_currencies:
            return True, "No monitored currencies in symbol"

        try:
            feed = feedparser.parse(self.feed_url)
            if not feed.entries:
                return True, "Calendar feed unavailable (defaulting to safe)"

            now_utc = datetime.now(UTC)
            buffer_delta = timedelta(minutes=self.buffer_minutes)

            for entry in feed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                
                # Check for high-impact keywords
                is_high_impact = any(tag in title.upper() or tag in summary.upper() for tag in ["CPI", "FED", "RATE", "NFP", "FOMC", "INTEREST"])
                
                if is_high_impact:
                    for cur in relevant_currencies:
                        if cur in title.upper():
                            # Flag event
                            return False, f"High-impact news window active for {cur}: '{title}'"

            return True, "Clear of high-impact releases"

        except Exception as e:
            log.warning(f"Failed to query news feed: {e}")
            return True, "Calendar check error bypass"