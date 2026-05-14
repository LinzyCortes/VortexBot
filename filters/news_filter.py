# ============================================
# VORTEX BOT - NEWS & SESSION FILTER
# ============================================

import requests
from datetime import datetime, timezone, timedelta
from logger import logger

WIB = timezone(timedelta(hours=7))
UTC = timezone.utc


class NewsFilter:
    def __init__(self):
        self.urls = [
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json",
        ]
        self.cache        = []
        self.cache_time   = None
        self.cache_expiry = 3600
        self.fail_count   = 0
        self.max_fails    = 3

    def _fetch_news(self) -> list:
        try:
            if (self.cache and self.cache_time and
                    (datetime.now() -
                     self.cache_time).seconds < self.cache_expiry):
                return self.cache

            if self.fail_count >= self.max_fails:
                logger.debug(
                    "📰 News fetch skipped (too many fails) "
                    "→ assuming safe to trade"
                )
                return self.cache or []

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
                                f"📰 News fetched: {len(data)} events"
                            )
                            return self.cache
                except Exception:
                    continue

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
        try:
            news_list   = self._fetch_news()
            now_utc     = datetime.now(UTC).replace(tzinfo=None)
            unsafe_news = []

            for news in news_list:
                impact = str(news.get("impact", "")).lower()
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

                window_start = news_time - timedelta(minutes=minutes_before)
                window_end   = news_time + timedelta(minutes=minutes_after)

                if window_start <= now_utc <= window_end:
                    safe_at_wib = window_end + timedelta(hours=7)
                    unsafe_news.append({
                        "title"      : news.get("title", ""),
                        "time"       : time_str,
                        "impact"     : impact,
                        "country"    : news.get("country", ""),
                        "safe_at_wib": safe_at_wib.strftime("%H:%M WIB"),
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
                "checked_at" : now_utc.isoformat(),
            }

        except Exception as e:
            logger.error(f"❌ News check error: {e}")
            return {"is_safe": True, "unsafe_news": []}

    def get_blocking_news(self,
                          minutes_before: int = 30,
                          minutes_after : int = 30) -> dict:
        try:
            status = self.is_safe_to_trade(minutes_before, minutes_after)
            if status["is_safe"]:
                return {
                    "is_blocking": False,
                    "news_list"  : [],
                    "safe_resume": None,
                }

            unsafe      = status["unsafe_news"]
            latest_safe = None

            for n in unsafe:
                safe_str = n.get("safe_at_wib", "")
                if safe_str:
                    try:
                        t = datetime.strptime(safe_str, "%H:%M WIB")
                        if latest_safe is None or t > latest_safe:
                            latest_safe = t
                    except Exception:
                        pass

            safe_resume = (
                latest_safe.strftime("%H:%M WIB")
                if latest_safe else "N/A"
            )

            return {
                "is_blocking": True,
                "news_list"  : unsafe,
                "safe_resume": safe_resume,
            }

        except Exception as e:
            logger.error(f"❌ get_blocking_news error: {e}")
            return {
                "is_blocking": False,
                "news_list"  : [],
                "safe_resume": None,
            }

    def get_upcoming_news(self, hours_ahead: int = 12) -> list:
        try:
            news_list = self._fetch_news()
            now_utc   = datetime.now(UTC).replace(tzinfo=None)
            upcoming  = []

            for news in news_list:
                impact = str(news.get("impact", "")).lower()
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

                if now_utc <= news_time <= now_utc + timedelta(hours=hours_ahead):
                    mins_away = int(
                        (news_time - now_utc).total_seconds() / 60
                    )
                    news_wib = news_time + timedelta(hours=7)
                    upcoming.append({
                        "title"       : news.get("title", ""),
                        "time_utc"    : time_str,
                        "time_wib"    : news_wib.strftime("%H:%M WIB"),
                        "country"     : news.get("country", ""),
                        "minutes_away": mins_away,
                    })

            return sorted(upcoming, key=lambda x: x["minutes_away"])

        except Exception as e:
            logger.error(f"❌ Upcoming news error: {e}")
            return []


class SessionFilter:
    """
    Semua jam dalam WIB (Asia/Jakarta, UTC+7).

    Killzone schedule:
      London   : 15:00 – 17:30 WIB
      New York : 20:30 – 23:00 WIB

    FIX v1.1: Killzone transition state sekarang persistent
    ke DB supaya tidak reset setiap Railway redeploy.
    Sebelumnya pakai instance variable (_notified_start set)
    yang hilang setiap restart → NY killzone tidak pernah
    kirim notif karena state selalu fresh.
    """

    def __init__(self):
        self.sessions = {
            "london": {
                "open"    : (15,  0),
                "close"   : (17, 30),
                "pre_open": (14, 45),
                "name"    : "London Killzone",
                "pre_name": "Pre-London",
            },
            "new_york": {
                "open"    : (20, 30),
                "close"   : (23,  0),
                "pre_open": (20, 15),
                "name"    : "New York Killzone",
                "pre_name": "Pre-NY",
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

        # ── DB import lazy supaya tidak circular ─────────────────────────────
        # State disimpan ke DB bukan instance variable supaya
        # persistent setelah Railway redeploy / restart.
        self._db = None

    def _get_db(self):
        """Lazy import DB untuk hindari circular import"""
        if self._db is None:
            try:
                from database import db
                self._db = db
            except Exception:
                self._db = None
        return self._db

    # ─── DB STATE HELPERS ───────────────────

    def _get_kz_state(self) -> dict:
        """
        Ambil killzone notif state dari DB.
        Format: {
            "notified_start": ["london", "new_york"],
            "notified_end"  : ["london"],
            "last_active"   : "london",
            "date"          : "2026-05-13",   ← reset tiap hari
        }
        """
        db = self._get_db()
        if not db:
            return {
                "notified_start": [],
                "notified_end"  : [],
                "last_active"   : None,
                "date"          : "",
            }

        today = datetime.now(WIB).strftime("%Y-%m-%d")
        state = db.get_state("kz_notif_state")

        # Reset state setiap hari baru supaya notif bisa
        # dikirim lagi keesokan harinya
        if not state or state.get("date") != today:
            fresh = {
                "notified_start": [],
                "notified_end"  : [],
                "last_active"   : None,
                "date"          : today,
            }
            db.set_state("kz_notif_state", fresh)
            return fresh

        return state

    def _save_kz_state(self, state: dict):
        """Simpan killzone notif state ke DB"""
        db = self._get_db()
        if db:
            db.set_state("kz_notif_state", state)

    # ─── KILLZONE CHECK ─────────────────────

    def _now_wib(self):
        now_wib  = datetime.now(WIB)
        hour_wib = now_wib.hour
        minute   = now_wib.minute
        weekday  = now_wib.weekday()
        return now_wib, hour_wib, minute, weekday

    def is_killzone(self) -> dict:
        """Cek apakah sekarang dalam killzone"""
        _, hour_wib, minute, _ = self._now_wib()
        now_min = hour_wib * 60 + minute

        for key, session in self.sessions.items():
            open_min  = session["open"][0]  * 60 + session["open"][1]
            close_min = session["close"][0] * 60 + session["close"][1]
            pre_min   = session["pre_open"][0] * 60 + session["pre_open"][1]

            if open_min <= now_min <= close_min:
                return {
                    "in_killzone"   : True,
                    "session"       : session["name"],
                    "session_key"   : key,
                    "minutes_left"  : close_min - now_min,
                    "is_pre_session": False,
                }

            if pre_min <= now_min < open_min:
                return {
                    "in_killzone"    : False,
                    "session"        : None,
                    "session_key"    : key,
                    "is_pre_session" : True,
                    "pre_name"       : session["pre_name"],
                    "minutes_to_open": open_min - now_min,
                    "next_session"   : {
                        "name"        : session["name"],
                        "minutes_away": open_min - now_min,
                    },
                }

        next_s = self._get_next_session(now_min)
        return {
            "in_killzone"   : False,
            "session"       : None,
            "is_pre_session": False,
            "next_session"  : next_s,
        }

    # ─── KILLZONE TRANSITION ────────────────

    def check_killzone_transition(self) -> dict:
        """
        Cek apakah ada transisi killzone yang perlu dinotifikasi.

        FIX v1.1: State sekarang persistent ke DB.
        Sebelumnya: instance variable → reset setiap Railway
        restart → NY killzone tidak pernah notif karena
        kondisi 'key not in _notified_start' selalu True
        tapi check di main loop tidak trigger Telegram.

        Sekarang: state disimpan ke DB per-hari, auto-reset
        tiap hari baru supaya notif bisa jalan lagi esoknya.
        """
        try:
            kz        = self.is_killzone()
            _, hour_wib, minute, _ = self._now_wib()
            wib_time  = f"{hour_wib:02d}:{minute:02d} WIB"

            # Ambil state dari DB
            state           = self._get_kz_state()
            notified_start  = set(state.get("notified_start", []))
            notified_end    = set(state.get("notified_end",   []))
            last_active     = state.get("last_active")

            if kz["in_killzone"]:
                key     = kz["session_key"]
                session = kz["session"]

                if key not in notified_start:
                    # Pertama kali masuk killzone ini hari ini → kirim notif
                    notified_start.add(key)
                    notified_end.discard(key)
                    state["notified_start"] = list(notified_start)
                    state["notified_end"]   = list(notified_end)
                    state["last_active"]    = key
                    self._save_kz_state(state)

                    logger.info(
                        f"🔔 Killzone STARTED: {session} | {wib_time}"
                    )
                    return {
                        "event"       : "started",
                        "session_key" : key,
                        "session"     : session,
                        "wib_time"    : wib_time,
                        "minutes_left": kz.get("minutes_left", 0),
                    }

                # Update last_active kalau belum
                if state.get("last_active") != key:
                    state["last_active"] = key
                    self._save_kz_state(state)

            else:
                # Cek apakah baru keluar dari killzone
                if (last_active and
                        last_active in notified_start and
                        last_active not in notified_end):

                    session_cfg      = self.sessions.get(last_active, {})
                    close_h, close_m = session_cfg.get("close", (0, 0))
                    now_min          = hour_wib * 60 + minute
                    close_min        = close_h  * 60 + close_m

                    if now_min > close_min:
                        notified_end.add(last_active)
                        notified_start.discard(last_active)
                        state["notified_start"] = list(notified_start)
                        state["notified_end"]   = list(notified_end)
                        state["last_active"]    = None
                        self._save_kz_state(state)

                        session_name = session_cfg.get("name", last_active)
                        logger.info(
                            f"🔔 Killzone ENDED: {session_name} | {wib_time}"
                        )
                        return {
                            "event"      : "ended",
                            "session_key": last_active,
                            "session"    : session_name,
                            "wib_time"   : wib_time,
                        }

            return {"event": None}

        except Exception as e:
            logger.error(f"❌ check_killzone_transition error: {e}")
            return {"event": None}

    # ─── HELPERS ────────────────────────────

    def _get_next_session(self, current_min: int) -> dict:
        candidates = []
        for key, session in self.sessions.items():
            open_min = session["open"][0] * 60 + session["open"][1]
            if open_min > current_min:
                candidates.append({
                    "name"        : session["name"],
                    "minutes_away": open_min - current_min,
                })
        if candidates:
            return min(candidates, key=lambda x: x["minutes_away"])

        london_open = (
            self.sessions["london"]["open"][0] * 60 +
            self.sessions["london"]["open"][1]
        )
        return {
            "name"        : "London Killzone (besok)",
            "minutes_away": (24 * 60 - current_min) + london_open,
        }

    def is_avoid_time(self) -> dict:
        _, hour_wib, minute, weekday = self._now_wib()
        now_min = hour_wib * 60 + minute

        for avoid in self.avoid_times:
            if avoid["day"] != weekday:
                continue
            start = avoid["start"][0] * 60 + avoid["start"][1]
            end   = avoid["end"][0]   * 60 + avoid["end"][1]
            if start <= now_min <= end:
                return {
                    "should_avoid": True,
                    "reason"      : avoid["reason"],
                }

        return {"should_avoid": False, "reason": None}

    def get_session_info(self) -> dict:
        now_wib_dt, hour_wib, minute, _ = self._now_wib()

        if 0 <= hour_wib < 7:
            active = "Asia Session (Low Volume)"
        elif 7 <= hour_wib < 14:
            active = "Pre-London (Preparation)"
        elif hour_wib == 14 and minute >= 45:
            active = "Pre-London Buffer ⏳"
        elif (hour_wib == 15 or hour_wib == 16 or
              (hour_wib == 17 and minute <= 30)):
            active = "London Killzone ⚡"
        elif 17 <= hour_wib < 20:
            active = "London-NY Gap"
        elif hour_wib == 20 and minute < 30:
            active = "Pre-NY Buffer ⏳"
        elif ((hour_wib == 20 and minute >= 30) or
              21 <= hour_wib < 23):
            active = "New York Killzone ⚡"
        else:
            active = "Late NY / Pre-Asia"

        killzone = self.is_killzone()
        avoid    = self.is_avoid_time()

        return {
            "active_session": active,
            "in_killzone"   : killzone["in_killzone"],
            "session_name"  : killzone.get("session"),
            "is_pre_session": killzone.get("is_pre_session", False),
            "should_avoid"  : avoid["should_avoid"],
            "avoid_reason"  : avoid.get("reason"),
            "wib_time"      : f"{hour_wib:02d}:{minute:02d} WIB",
            "utc_time"      : datetime.now(UTC).strftime("%H:%M UTC"),
        }


# Instances siap pakai
news_filter    = NewsFilter()
session_filter = SessionFilter()