# ============================================
# VORTEX BOT - NEWS FILTER
# ============================================

import requests
from datetime import datetime, timedelta
from logger import logger


class NewsFilter:
    def __init__(self):
        self.url = (
            "https://nfs.faireconomy.media"
            "/ff_calendar_thisweek.json"
        )
        self.cache         = []
        self.cache_time    = None
        self.cache_expiry  = 3600  # 1 jam

        # Keyword high impact news
        self.high_impact_keywords = [
            "NFP", "Non-Farm", "CPI", "Inflation",
            "FOMC", "Fed", "Interest Rate", "GDP",
            "Unemployment", "Retail Sales", "PPI",
            "Powell", "ECB", "BOE", "BOJ",
        ]

    # ─── FETCH NEWS ─────────────────────────

    def _fetch_news(self) -> list:
        """Fetch news dari Forex Factory"""
        try:
            # Pakai cache kalau masih valid
            if (self.cache and self.cache_time and
                    (datetime.now() - self.cache_time).seconds
                    < self.cache_expiry):
                return self.cache

            response = requests.get(
                self.url, timeout=10
            )
            if response.status_code == 200:
                self.cache      = response.json()
                self.cache_time = datetime.now()
                logger.debug(
                    f"📰 News fetched: {len(self.cache)} events"
                )
                return self.cache
            return []

        except Exception as e:
            logger.warning(f"⚠️ News fetch failed: {e}")
            return []

    # ─── CHECK NEWS ─────────────────────────

    def is_safe_to_trade(self,
                         minutes_before: int = 30,
                         minutes_after:  int = 30) -> dict:
        """
        Cek apakah aman untuk trading sekarang.
        Returns dict dengan status dan info news.
        """
        try:
            news_list = self._fetch_news()
            now       = datetime.utcnow()

            unsafe_news = []

            for news in news_list:
                # Skip jika bukan high impact
                impact = news.get("impact", "").lower()
                if impact != "high":
                    continue

                # Parse waktu news
                news_time_str = news.get("date", "")
                if not news_time_str:
                    continue

                try:
                    news_time = datetime.strptime(
                        news_time_str, "%Y-%m-%dT%H:%M:%S%z"
                    ).replace(tzinfo=None)
                except:
                    continue

                # Cek window waktu
                window_start = news_time - timedelta(
                    minutes=minutes_before
                )
                window_end   = news_time + timedelta(
                    minutes=minutes_after
                )

                if window_start <= now <= window_end:
                    unsafe_news.append({
                        "title"  : news.get("title", ""),
                        "time"   : news_time_str,
                        "impact" : impact,
                        "country": news.get("country", ""),
                    })

            is_safe = len(unsafe_news) == 0

            if not is_safe:
                logger.warning(
                    f"⚠️ NEWS FILTER: {len(unsafe_news)} "
                    f"high impact news detected! Skip trading."
                )
                for n in unsafe_news:
                    logger.warning(
                        f"   📰 {n['title']} @ {n['time']}"
                    )

            return {
                "is_safe"     : is_safe,
                "unsafe_news" : unsafe_news,
                "checked_at"  : now.isoformat(),
            }

        except Exception as e:
            logger.error(f"❌ News check error: {e}")
            # Default aman jika error fetch
            return {"is_safe": True, "unsafe_news": []}

    def get_upcoming_news(self,
                          hours_ahead: int = 4) -> list:
        """Ambil news yang akan datang dalam X jam"""
        try:
            news_list = self._fetch_news()
            now       = datetime.utcnow()
            upcoming  = []

            for news in news_list:
                impact = news.get("impact", "").lower()
                if impact != "high":
                    continue

                news_time_str = news.get("date", "")
                if not news_time_str:
                    continue

                try:
                    news_time = datetime.strptime(
                        news_time_str, "%Y-%m-%dT%H:%M:%S%z"
                    ).replace(tzinfo=None)
                except:
                    continue

                # Cek apakah dalam X jam ke depan
                if now <= news_time <= now + timedelta(
                    hours=hours_ahead
                ):
                    upcoming.append({
                        "title"      : news.get("title", ""),
                        "time"       : news_time_str,
                        "country"    : news.get("country", ""),
                        "minutes_away": int(
                            (news_time - now).seconds / 60
                        ),
                    })

            return upcoming

        except Exception as e:
            logger.error(f"❌ Upcoming news error: {e}")
            return []


# ============================================
# VORTEX BOT - SESSION / KILLZONE FILTER
# ============================================

class SessionFilter:
    def __init__(self):
        # Killzone dalam jam WIB (UTC+7)
        self.sessions = {
            "london": {
                "open" : (14, 0),   # 14:00 WIB
                "close": (17, 0),   # 17:00 WIB
                "name" : "London Killzone"
            },
            "new_york": {
                "open" : (19, 30),  # 19:30 WIB
                "close": (23, 0),   # 23:00 WIB
                "name" : "New York Killzone"
            }
        }

        # Waktu yang dihindari
        self.avoid_times = [
            # Monday open (market gap)
            {"day": 0, "start": (0, 0),  "end": (2, 0),
             "reason": "Monday Open - market gap risk"},
            # Friday close
            {"day": 4, "start": (22, 0), "end": (23, 59),
             "reason": "Friday Close - low volume"},
        ]

    def is_killzone(self) -> dict:
        """Cek apakah sekarang dalam killzone"""
        # WIB = UTC + 7
        now_wib  = datetime.utcnow()
        now_hour = (now_wib.hour + 7) % 24
        now_min  = now_wib.minute
        now_time = now_hour * 60 + now_min  # dalam menit

        for session_name, session in self.sessions.items():
            open_time  = (session["open"][0]  * 60 +
                          session["open"][1])
            close_time = (session["close"][0] * 60 +
                          session["close"][1])

            if open_time <= now_time <= close_time:
                minutes_left = close_time - now_time
                return {
                    "in_killzone"  : True,
                    "session"      : session["name"],
                    "session_key"  : session_name,
                    "minutes_left" : minutes_left,
                }

        # Hitung next killzone
        next_session = self._get_next_session(now_time)
        return {
            "in_killzone" : False,
            "session"     : None,
            "next_session": next_session,
        }

    def _get_next_session(self, current_minutes: int) -> dict:
        """Hitung sesi berikutnya"""
        sessions_today = []
        for key, session in self.sessions.items():
            open_time = (session["open"][0]  * 60 +
                         session["open"][1])
            if open_time > current_minutes:
                sessions_today.append({
                    "name"           : session["name"],
                    "minutes_away"   : open_time - current_minutes,
                })

        if sessions_today:
            return min(sessions_today,
                       key=lambda x: x["minutes_away"])
        return {"name": "London (besok)", "minutes_away": 0}

    def is_avoid_time(self) -> dict:
        """Cek apakah sekarang waktu yang dihindari"""
        now_wib  = datetime.utcnow()
        now_hour = (now_wib.hour + 7) % 24
        now_min  = now_wib.minute
        now_day  = now_wib.weekday()  # 0=Monday, 6=Sunday
        now_time = now_hour * 60 + now_min

        for avoid in self.avoid_times:
            if avoid["day"] != now_day:
                continue

            start = (avoid["start"][0] * 60 +
                     avoid["start"][1])
            end   = (avoid["end"][0]   * 60 +
                     avoid["end"][1])

            if start <= now_time <= end:
                return {
                    "should_avoid": True,
                    "reason"      : avoid["reason"],
                }

        return {"should_avoid": False, "reason": None}

    def get_session_info(self) -> dict:
        """Info lengkap sesi sekarang"""
        now_wib  = datetime.utcnow()
        now_hour = (now_wib.hour + 7) % 24

        # Tentukan sesi aktif
        if 0 <= now_hour < 7:
            active_session = "Asia Session (Low Volume)"
        elif 7 <= now_hour < 14:
            active_session = "Pre-London (Preparation)"
        elif 14 <= now_hour < 17:
            active_session = "London Killzone ⚡"
        elif 17 <= now_hour < 19:
            active_session = "London-NY Overlap"
        elif 19 <= now_hour < 23:
            active_session = "New York Killzone ⚡"
        else:
            active_session = "Late NY / Pre-Asia"

        killzone = self.is_killzone()
        avoid    = self.is_avoid_time()

        return {
            "active_session" : active_session,
            "in_killzone"    : killzone["in_killzone"],
            "session_name"   : killzone.get("session"),
            "should_avoid"   : avoid["should_avoid"],
            "avoid_reason"   : avoid.get("reason"),
            "wib_time"       : f"{now_hour:02d}:{now_wib.minute:02d}",
        }


# Instances siap pakai
news_filter    = NewsFilter()
session_filter = SessionFilter()