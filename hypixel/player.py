import aiohttp
import asyncio
import math
import minepi
import typing

from discord.ext.commands import MemberConverter
from redbot.core import commands
from typing import Optional, Tuple, Union, Final

from .utils.enums import Gamemodes, Gamemode, Ranks, Scope

if typing.TYPE_CHECKING:
    import discord

    from PIL import Image
    from redbot.core import Config

USER_AGENT: Final = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " \
                    "AppleWebKit/537.36 (KHTML, like Gecko) " \
                    "Chrome/93.0.4577.82 Safari/537.36"


class HypixelPlayer(minepi.Player):
    """Class representing a single hypixel player"""
    session: Optional[aiohttp.ClientSession] = None
    config: Optional["Config"] = None
    bot: Optional[commands.Bot] = None

    def __init__(
            self,
            user_identifier: Union[str, "discord.Member"],
            ctx: commands.Context = None,
            guild: "discord.Guild" = None,
    ):
        self._ctx = ctx
        self._user_identifier = user_identifier
        self._player_ready: asyncio.Event = asyncio.Event()

        self._guild = ctx.guild if ctx else guild
        self._uuid: Optional[str] = None
        self._user: Optional["discord.Member"] = None
        self._skin: Optional["Image.Image"] = None
        self._xp: Optional[int] = None
        self._resp: Optional[dict] = None
        self._color: Optional[Tuple] = None
        self._rank: Optional[Ranks] = Ranks.DEFAULT
        self._valid: bool = False

        self._apikey: Optional[str] = None
        self._apikey_scope: Optional[Scope] = None

        self.bot.loop.create_task(self.initialize())

    @property
    def rank(self):
        """Returns the player's Hypixel rank"""
        return self._rank

    @property
    def valid(self):
        """Returns True if there is a UUID associated to this object"""
        return self._valid

    async def wait_for_fully_constructed(self):
        """Returns true as soon as the object is fully constructed"""
        await self._player_ready.wait()

    async def initialize(self):
        if not self._guild:
            self._player_ready.set()
            return

        await self.get_uuid()
        if not bool(self._uuid):
            self._player_ready.set()
            return

        self._apikey, self._apikey_scope = await self.fetch_apikey(
            ctx=self._ctx, guild=self._guild, user=self._user
        )

        if not self._apikey:
            self._player_ready.set()
            return

        await self.fetch_stats()

        if not self._resp:
            self._player_ready.set()
            return

        await self.fetch_user_data()
        self._valid = True
        self._player_ready.set()

    @classmethod
    async def request_hypixel(
            cls,
            apikey: str,
            uuid: str = None,
            topic: str = "player",
    ) -> Tuple[Optional[dict], Optional[int]]:
        url = f"https://api.hypixel.net/{topic}"

        if uuid:
            url += f"?uuid={uuid}"

        headers = {
            "API-Key": apikey,
            "User-Agent": USER_AGENT
        }

        async with cls.session.get(url=url, headers=headers) as resp:
            try:
                resp_dict = await resp.json()

                return resp_dict, resp.status
            except asyncio.TimeoutError:
                # api down again?
                return None, None

    @classmethod
    async def request_mojang(
            cls,
            mc_name: str,
    ) -> Tuple[Optional[dict], Optional[int]]:
        url = f"https://api.mojang.com/users/profiles/minecraft/{mc_name}"

        headers = {
            "User-Agent": USER_AGENT
        }
        async with cls.session.get(url=url, headers=headers) as resp:
            try:
                resp_dict = await resp.json()
                return resp_dict, resp.status
            except asyncio.TimeoutError:
                # api down again?
                return None, None

    @classmethod
    async def fetch_apikey(
            cls,
            ctx: commands.Context = None,
            user: Union["discord.User", "discord.Member"] = None,
            guild: "discord.Guild" = None,
    ) -> Tuple[Optional[str], Optional[Scope]]:
        """Guild/User based apikey lookup"""
        if not user:
            user = ctx.author if ctx else None
        if not guild:
            guild = ctx.guild if ctx else user.guild if isinstance(user, discord.Member) else None

        user_key = await cls.config.user(user).apikey() if user else None
        if not user_key and guild:
            guild_key = await cls.config.guild(guild).apikey()
            return guild_key, Scope.GLOBAL
        elif user_key:
            return user_key, Scope.USER
        else:
            return None, None

    def xp(self, gm: Gamemode = None) -> Tuple[int, float, int]:
        """Returns the player's network XP for the given gamemode"""
        if gm and gm.xp_key:
            xp = self.stats(gm).get(gm.xp_key, 0)
            if gm == Gamemodes.BEDWARS.value:
                levels_per_prestige: Final = 100
                level_cost: Final = 5000
                easy_level_cost = {1: 500, 2: 1000, 3: 2000, 4: 3500}
                easy_xp = sum(easy_level_cost.values())
                easy_levels = len(easy_level_cost)
                prestige_xp = easy_xp + (100 - easy_levels) * level_cost

                levels = (xp // prestige_xp) * levels_per_prestige
                xp %= prestige_xp

                for i in range(1, easy_levels + 1):
                    cost = easy_level_cost[i]
                    if xp >= cost:
                        levels += 1
                        xp -= cost
                    else:
                        break

                levels += xp // level_cost
                xp %= level_cost

                next_level = (levels + 1) % levels_per_prestige
                if next_level in easy_level_cost:
                    cost = easy_level_cost[next_level]
                else:
                    cost = level_cost

                return levels, xp / cost, cost

            elif gm == Gamemodes.SKYWARS.value:
                xps = [0, 20, 70, 150, 250, 500, 1000, 2000, 3500, 5000, 10000, 15000]
                easy_xp_skywars = 0
                for i in xps:
                    easy_xp_skywars += i
                if xp >= 15000:
                    level = (xp - 15000) / 10000 + 12
                    percentage = level % 1.0
                    return int(level), percentage, 15000
                else:
                    for i in range(len(xps)):
                        if xp < xps[i]:
                            level = i + float(xp - xps[i - 1]) / (xps[i] - xps[i - 1])
                            percentage = level % 1.0
                            return int(level), percentage, xps[i]

            return 0, 0, 0

        elif not gm:
            xp = self._resp.get("networkExp", 0)
            fraction, level = math.modf(math.sqrt((2 * xp) + 30625) / 50 - 2.5)
            return int(level), fraction, 0
        else:
            return 0, 0, 0

    def filtered_stats(self, gm: Gamemode, modules: list):
        if not self._resp:
            return

        stats = []
        for module in modules:
            if module.is_custom:
                stats.append(module.calculation)
            else:
                stats.append(self.stats(gm)[module.db_key])

        return stats

    def stats(self, gm: Gamemode):
        """Returns the player's stats for the given gamemode"""
        return self._resp["stats"].get(gm.db_key, {})

    async def get_uuid(self):
        if isinstance(self._user_identifier, discord.Member) or len(self._user_identifier) == 18:
            try:
                member_obj = await MemberConverter().convert(
                    self._guild, str(self._user_identifier), self._ctx.message.mentions if self._ctx else None
                )
                self._user = member_obj
                uuid = await self.config.user(member_obj).uuid()
                if uuid:
                    self._uuid = uuid
                    return

            except commands.BadArgument:
                pass

        else:
            # no MemberObject or ID was passed or the given user has no uuid set
            # trying a request to mojang servers
            resp, status = await self.request_mojang(self._user_identifier)

            if status == 200 and resp.get("id", None):
                # request successful, using the uuid returned
                self._uuid = resp["id"]
            else:
                # request not successful, trying to convert the rest
                try:
                    member_obj = await MemberConverter().convert(
                        self._guild, str(self._user_identifier), self._ctx.message.mentions if self._ctx else None
                    )

                    uuid = await self.config.user(member_obj).uuid()
                    if uuid:
                        self._user = member_obj
                        self._uuid = uuid
                        return

                except commands.BadArgument:
                    pass

    async def fetch_stats(self):
        if not self._uuid:
            return

        resp, status = await self.request_hypixel(
            apikey=self._apikey,
            uuid=self._uuid,
        )

        if status == 200 and resp and resp["success"]:
            self._resp = resp["player"] if resp["player"] else {}

    async def fetch_user_data(self):
        if isinstance(self._user, discord.Member):
            member_data = await self.config.user(self._user).all()
            self._skin = member_data["skin"]
            self._color = member_data["header_color"]

        else:
            self._color = await self.config.header_color()

        self._rank = Ranks.convert(self._resp)
