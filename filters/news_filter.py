# ============================================
# VORTEX BOT - NEWS & SESSION FILTER
# ============================================

import requests
from datetime import datetime, timedelta
from logger import logger


class NewsFilter:
    def __init__(self):
        self.urls = [
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json",
        ]
        self.cache        = []
        self.cache_time   = None
        self.cache_expiry = 3600  # 1 jam
        self.fetch_failed = False
        self.fail_count   = 0
        self.max_fails    = 3

    def _fetch_news(self) -> list:
        """Fetch news dengan multiple URL fallback"""
        try:
            # Pakai cache kalau masih valid
            if (self.cache and self.cache_time and
                    (datetime.now() -
                     self.cache_time).seconds < self.cache_expiry):
                return self.cache

            # Kalau sudah terlalu banyak gagal →
            # return cache lama atau empty
            if self.fail_count >= self.max_fails:
                logger.debug(
                    "📰 News fetch skipped (too many fails) "
                    "→ assuming safe to trade"
                )
                return self.cache or []

            # Coba semua URL
            for url in self.urls:
                try:
                    resp = requests.get(url, timeout=8)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, list):
                            self.cache      = data
                            self.cache_time = datetime.now()
                            self.fail_count = 0
                            logger.debug(
                                f"📰 News fetched: "
                                f"{len(data)} events"
                            )
                            return self.cache
                except Exception:
                    continue

            # Semua URL gagal
            self.fail_count += 1
            logger.warning(
                f"⚠️ News fetch failed "
                f"({self.fail_count}/{self.max_fails})"
            )
            return self.cache or []

        except Exception as e:
            logger.warning(f"⚠️ News error: {e}")
            return self.cache or []

    def is_safe_to_trade(self,
                         minutes_before: int = 30,
                         minutes_after : int = 30) -> dict:
        """Cek apakah aman trading"""
        try:
            news_list   = self._fetch_news()
            now         = datetime.utcnow()
            unsafe_news = []

            for news in news_list:
                impact = str(
                    news.get("impact", "")
                ).lower()
                if impact != "high":
                    continue

                time_str = news.get("date", "")
                if not time_str:
                    continue

                try:
                    news_time = datetime.strptime(
                        time_str, "%Y-%m-%dT%H:%M:%S%z"
                    ).replace(tzinfo=None)
                except Exception:
                    try:
                        news_time = datetime.strptime(
                            time_str, "%Y-%m-%dT%H:%M:%S"
                        )
                    except Exception:
                        continue

                window_start = news_time - timedelta(
                    minutes=minutes_before
                )
                window_end = news_time + timedelta(
                    minutes=minutes_after
                )

                if window_start <= now <= window_end:
                    unsafe_news.append({
                        "title"  : news.get("title", ""),
                        "time"   : time_str,
                        "impact" : impact,
                        "country": news.get("country", ""),
                    })

            is_safe = len(unsafe_news) == 0

            if not is_safe:
                logger.warning(
                    f"⚠️ NEWS FILTER: "
                    f"{len(unsafe_news)} high impact events!"
                )

            return {
                "is_safe"    : is_safe,
                "unsafe_news": unsafe_news,
                "checked_at" : now.isoformat(),
            }

        except Exception as e:
            logger.error(f"❌ News check error: {e}")
            # Default AMAN kalau error
            return {"is_safe": True, "unsafe_news": []}

    def get_upcoming_news(self,
                          hours_ahead: int = 12) -> list:
        """Ambil news upcoming"""
        try:
            news_list = self._fetch_news()
            now       = datetime.utcnow()
            upcoming  = []

            for news in news_list:
                impact = str(
                    news.get("impact", "")
                ).lower()
                if impact != "high":
                    continue

                time_str = news.get("date", "")
                if not time_str:
                    continue

                try:
                    news_time = datetime.strptime(
                        time_str, "%Y-%m-%dT%H:%M:%S%z"
                    ).replace(tzinfo=None)
                except Exception:
                    try:
                        news_time = datetime.strptime(
                            time_str, "%Y-%m-%dT%H:%M:%S"
                        )
                    except Exception:
                        continue

                if now <= news_time <= now + timedelta(
                    hours=hours_ahead
                ):
                    mins_away = int(
                        (news_time - now).total_seconds() / 60
                    )
                    upcoming.append({
                        "title"      : news.get("title", ""),
                        "time"       : time_str,
                        "country"    : news.get("country", ""),
                        "minutes_away": mins_away,
                    })

            return sorted(
                upcoming, key=lambda x: x["minutes_away"]
            )

        except Exception as e:
            logger.error(f"❌ Upcoming news error: {e}")
            return []


class SessionFilter:
    def __init__(self):
        self.sessions = {
            "london": {
                "open" : (14, 0),
                "close": (17, 0),
                "name" : "London Killzone",
            },
            "new_york": {
                "open" : (19, 30),
                "close": (23, 0),
                "name" : "New York Killzone",
            },
        }
        self.avoid_times = [
            {
                "day"   : 0,
                "start" : (0, 0),
                "end"   : (2, 0),
                "reason": "Monday Open — gap risk",
            },
            {
                "day"   : 4,
                "start" : (22, 0),
                "end"   : (23, 59),
                "reason": "Friday Close — low volume",
            },
        ]

    def _now_wib(self):
        """Waktu sekarang dalam WIB"""
        now      = datetime.utcnow()
        hour_wib = (now.hour + 7) % 24
        return now, hour_wib, now.minute, now.weekday()

    def is_killzone(self) -> dict:
        """Cek killzone"""
        _, hour_wib, minute, _ = self._now_wib()
        now_min = hour_wib * 60 + minute

        for key, session in self.sessions.items():
            open_min  = session["open"][0]  * 60 + \
                        session["open"][1]
            close_min = session["close"][0] * 60 + \
                        session["close"][1]

            if open_min <= now_min <= close_min:
                return {
                    "in_killzone" : True,
                    "session"     : session["name"],
                    "session_key" : key,
                    "minutes_left": close_min - now_min,
                }

        next_s = self._get_next_session(now_min)
        return {
            "in_killzone" : False,
            "session"     : None,
            "next_session": next_s,
        }

    def _get_next_session(self,
                          current_min: int) -> dict:
        """Hitung sesi berikutnya"""
        candidates = []
        for key, session in self.sessions.items():
            open_min = session["open"][0] * 60 + \
                       session["open"][1]
            if open_min > current_min:
                candidates.append({
                    "name"       : session["name"],
                    "minutes_away": open_min - current_min,
                })
        if candidates:
            return min(
                candidates, key=lambda x: x["minutes_away"]
            )
        # Besok London
        london_open = (
            self.sessions["london"]["open"][0] * 60 +
            self.sessions["london"]["open"][1]
        )
        return {
            "name"        : "London Killzone (besok)",
            "minutes_away": (24*60 - current_min) + london_open,
        }

    def is_avoid_time(self) -> dict:
        """Cek waktu yang dihindari"""
        _, hour_wib, minute, weekday = self._now_wib()
        now_min = hour_wib * 60 + minute

        for avoid in self.avoid_times:
            if avoid["day"] != weekday:
                continue
            start = avoid["start"][0]*60 + avoid["start"][1]
            end   = avoid["end"][0]  *60 + avoid["end"][1]
            if start <= now_min <= end:
                return {
                    "should_avoid": True,
                    "reason"      : avoid["reason"],
                }

        return {"should_avoid": False, "reason": None}

    def get_session_info(self) -> dict:
        """Info lengkap sesi sekarang"""
        _, hour_wib, minute, _ = self._now_wib()

        if 0 <= hour_wib < 7:
            active = "Asia Session (Low Volume)"
        elif 7 <= hour_wib < 14:
            active = "Pre-London (Preparation)"
        elif 14 <= hour_wib < 17:
            active = "London Killzone ⚡"
        elif 17 <= hour_wib < 19:
            active = "London-NY Overlap"
        elif 19 <= hour_wib < 23:
            active = "New York Killzone ⚡"
        else:
            active = "Late NY / Pre-Asia"

        killzone = self.is_killzone()
        avoid    = self.is_avoid_time()

        return {
            "active_session": active,
            "in_killzone"   : killzone["in_killzone"],
            "session_name"  : killzone.get("session"),
            "should_avoid"  : avoid["should_avoid"],
            "avoid_reason"  : avoid.get("reason"),
            "wib_time"      : f"{hour_wib:02d}:{minute:02d}",
        }


# Instances siap pakai
news_filter    = NewsFilter()
session_filter = SessionFilter()