import aiohttp
import asyncio
import math
import discord
import json
import MinePI
import pathlib
import random

from io import BytesIO
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageColor
from typing import Optional, Tuple, Final, Union, List, Any

from redbot.core import commands, Config
from redbot.core.utils import AsyncIter
from redbot.core.data_manager import cog_data_path, bundled_data_path
from redbot.core.utils.chat_formatting import box

from .utils.abc import CompositeMetaClass, MixinMeta
from .utils.enums import gamemode, gamemodes, scope, colortypes, Ranks

INVALID_API_KEY: Final = "Invalid API key"
USER_AGENT: Final = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36"

"""Api requests"""
async def request_hypixel(
        session: aiohttp.ClientSession,
        apikey: str,
        ctx: commands.Context = None,
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

    async with session.get(url=url, headers=headers) as resp:
        try:
            resp_dict = json.loads(await resp.text())

            return resp_dict, resp.status
        except json.JSONDecodeError:
            # invalid response?
            print(resp.status)
            return None, resp.status
        except AttributeError:
            # api down again?
            return None, resp.status
        except asyncio.TimeoutError:
            # api down again?
            return None, None


async def request_mojang(
        mc_name: str,
        session: aiohttp.ClientSession,
) -> Tuple[Optional[dict], Optional[int]]:
    url = f"https://api.mojang.com/users/profiles/minecraft/{mc_name}"

    headers = {
        "User-Agent": USER_AGENT
    }
    async with session.get(url=url, headers=headers) as resp:
        try:
            resp_dict = json.loads(await resp.text())
            return resp_dict, resp.status
        except json.JSONDecodeError:
            # invalid response?
            return None, resp.status
        except asyncio.TimeoutError:
            # api down again?
            return None, None


async def fetch_apikey(ctx: commands.Context, config: Config) -> Tuple[Optional[str], scope]:
    """Guild/User based apikey lookup"""
    user_key = await config.user(ctx.author).apikey()
    if not user_key and ctx.guild:
        guild_key = await config.guild(ctx.guild).apikey()
        return guild_key, scope.GLOBAL
    else:
        return user_key, scope.USER


class Module:
    """Class representing a single module"""
    all_modules: Optional[dict] = None

    def __init__(self):
        self._name: Optional[str] = None
        self._db_key: Optional[str] = None
        self._value: Optional[Any] = None
    
    @property
    def name(self):
        return self._name
    
    @property
    def db_key(self):
        return self._db_key

    @property
    def value(self):
        return self._value

    @property
    def is_custom(self):
        if not self._db_key:
            return True

        return False
    
    def get_value(self):
        if self._db_key in Module.all_modules:
            return


class Player:
    """Class representing a single hypixel player"""
    def __init__(
            self,
            ctx: commands.Context,
            user_identifier: Union[str, discord.Member],
            config: Config,
            session: aiohttp.ClientSession,
    ):
        self._session = session
        self._ctx = ctx
        self._user_identifier = user_identifier
        self._config: Config = config
        self._player_ready: asyncio.Event = asyncio.Event()

        self._guild = ctx.guild
        self._uuid: Optional[str] = None
        self._user: Optional[discord.Member] = None
        self._skin: Optional[Image.Image] = None
        self._xp: Optional[int] = None
        self._stats: Optional[dict] = None
        self._color: Optional[Tuple] = None
        self._rank: Optional[str] = "Default"

        self._apikey: Optional[str] = None
        self._apikey_scope: Optional[scope] = None

        ctx.bot.loop.create_task(self.initialize())

    @property
    def rank(self):
        """Returns the player's Hypixel rank"""
        return self._rank

    @property
    def skin(self):
        """Returns the player's raw skin"""
        return self._skin

    @property
    def uuid(self):
        """Returns the UUID associated to this object"""
        return self._uuid

    @property
    def valid(self):
        """Returns True if there is a UUID associated to this object"""
        return not not self._uuid

    async def wait_for_fully_constructed(self):
        """Returns true as soon as the object is fully constructed"""
        await self._player_ready.wait()

    def xp(self, gm: gamemode = None) -> Tuple[int, float]:
        """Returns the player's network XP for the given gamemode"""
        if gm and gm.xp_key:
            xp = self._stats["stats"].get(gm.xp_key, 0)
            if gm == gamemodes.BEDWARS.value:
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

                return levels, xp / cost

            elif gm == gamemodes.SKYWARS.value:
                xps = [0, 20, 70, 150, 250, 500, 1000, 2000, 3500, 5000, 10000, 15000]
                easy_xp_skywars = 0
                for i in xps:
                    easy_xp_skywars += i
                if xp >= 15000:
                    level = (xp - 15000) / 10000 + 12
                    percentage = level % 1.0
                    return int(level), percentage
                else:
                    for i in range(len(xps)):
                        if xp < xps[i]:
                            level = i + float(xp - xps[i - 1]) / (xps[i] - xps[i - 1])
                            percentage = level % 1.0
                            return int(level), percentage

        elif not gm:
            xp = self._stats.get("networkExp", 0)
            fraction, level = math.modf(math.sqrt((2 * xp) + 30625) / 50 - 2.5)
            return int(level), fraction
        else:
            return 0, 0

    def stats(self, gm: gamemode):
        """Returns the player's stats for the given gamemode"""
        return self._stats["stats"].get(gm.db_key, None)

    def filtered_stats(self, gm: gamemode, modules: list):
        """Returns the player's stats for the given modules of a gamemode"""
        if not self.stats(gm):
            return

        return [self.stats(gm).get(i[0], 0) for i in modules]

    async def initialize(self):
        await self.get_uuid()
        self._apikey, self._apikey_scope = await fetch_apikey(self._ctx, self._config)

        if not self._apikey:
            return

        await self.fetch_stats()
        await self.fetch_user_data()
        self._player_ready.set()

    async def get_uuid(self):
        if isinstance(self._user_identifier, discord.Member) or len(self._user_identifier) == 18:
            try:
                member_obj = await commands.MemberConverter().convert(self._ctx, str(self._user_identifier))
                uuid = await self._config.user(member_obj).uuid()
                if uuid:
                    self._user = member_obj
                    self._uuid = uuid
                    return

            except commands.BadArgument:
                pass

        # no MemberObject or ID was passed or the given user has no uuid set
        # trying a request to mojang servers
        resp, status = await request_mojang(self._user_identifier, self._session)

        if status == 200 and resp.get("id", None):
            # request successful, using the uuid returned
            self._uuid = resp["id"]
        else:
            # request not successful, trying to convert the rest
            try:
                member_obj = await commands.MemberConverter().convert(self._ctx, str(self._user_identifier))

                uuid = await self._config.user(member_obj).uuid()
                if uuid:
                    self._user = member_obj
                    self._uuid = uuid
                    return

            except commands.BadArgument:
                pass

    async def fetch_stats(self):
        if not self._uuid:
            return

        resp, status = await request_hypixel(
            session=self._session,
            apikey=self._apikey,
            uuid=self._uuid,
        )

        if status == 200 and resp and resp["success"]:
            self._stats = resp["player"]

    async def fetch_user_data(self):
        if self._user:
            member_data = await self._config.user(self._user).all()
            self._skin = member_data["skin"]
            self._color = member_data["header_color"]

        else:
            self._color = await self._config.header_color()

        package_rank = self._stats.get("rank")
        rank = self._stats.get("prefix")
        prefix_raw = self._stats.get("monthlyPackageRank")
        monthly_package_rank = self._stats.get("newPackageRank")
        new_package_rank = self._stats.get("packageRank")

        real_rank = None

        if rank and rank != "NORMAL" and not real_rank:
            real_rank = await Ranks.convert(None, rank)

        elif (monthly_package_rank and monthly_package_rank != "NONE") and not real_rank:
            real_rank = await Ranks.convert(None, monthly_package_rank)

        elif new_package_rank and not real_rank:
            real_rank = await Ranks.convert(None, new_package_rank)

        elif package_rank and not real_rank:
            real_rank = await Ranks.convert(None, package_rank)

        self._rank = real_rank


class Autostats:
    def __init__(self,
                 cog,
                 channel: discord.TextChannel,
                 gm: gamemodes,
                 user_data: dict,
                 apikey: str,
                 current_modules: list,
                 custom_modules: dict
            ):
        self.channel: discord.TextChannel = channel
        self.gamemode: gamemodes = gm
        self.user_data: list = user_data
        self.current_modules: list = current_modules
        self.custom_modules: dict = custom_modules
        self.cog: Hypixel = cog
        self.messages: list = []
        self.apikey: str = apikey

        self.task: asyncio.Task

    async def is_updated(self):
        stats, xp, _ = await self.cog.uuid_to_stats(
            uuid=self.user_data[0]["uuid"],
            gm=self.gamemode,
            active_modules=self.current_modules,
            custom_modules=self.custom_modules,
            apikey=self.apikey
        )

        if stats and stats[0] != self.user_data[0]["stats"][0]:
            self.user_data[0]["stats"] = stats
            self.user_data[0]["xp"] = xp
            return True
        else:
            return False

    async def main(self):
        try:
            while not self.task.cancelled():
                previous = self.user_data[0]["stats"]
                if await self.is_updated():
                    await self.maybe_delete_old_messages()
                    im_list = []

                    for idx, user in enumerate(self.user_data):
                        if idx:
                            previous = self.user_data[idx]["stats"]
                            stats, xp, _ = await self.cog.uuid_to_stats(
                                uuid=user["uuid"],
                                gm=self.gamemode,
                                active_modules=self.current_modules,
                                custom_modules=self.custom_modules,
                                apikey=self.apikey
                            )

                            self.user_data[idx]["stats"] = stats
                            self.user_data[idx]["xp"] = xp

                        im_list.append(await self.cog.create_stats_img(
                            user_data=user,
                            gm=self.gamemode,
                            compare_stats=previous
                        ))

                    self.messages = await self.cog.maybe_send_images(self.channel, im_list)
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    async def maybe_delete_old_messages(self):
        try:
            await self.channel.delete_messages(messages=self.messages)
            self.messages = []
        except (discord.Forbidden, discord.NotFound):
            pass

    def _exception_catching_callback(self, task: asyncio.Task):
        if task.exception():
            task.result()

    async def start(self):
        im_list = []
        for user in self.user_data:
            im_list.append(await self.cog.create_stats_img(user_data=user, gm=self.gamemode))

        self.messages = await self.cog.maybe_send_images(self.channel, im_list)

        if self.user_data:
            self.task = asyncio.create_task(self.main())
            self.task.add_done_callback(self._exception_catching_callback)

    async def cancel(self):
        await self.maybe_delete_old_messages()
        self.task.cancel()
        del self


class SelectionRow(discord.ui.Select):
    def __init__(self, current_modules: list, author: discord.Member, config: Config, gm: gamemode):
        self.config = config
        self.gamemode = gamemode
        self.author = author
        self.current_modules = current_modules

        options = []
        for i in current_modules:
            options.append(discord.SelectOption(label=i[0], description=i[1]))

        super().__init__(
            placeholder="Select the modules in the order you want...",
            options=options,
            min_values=len(current_modules),
            max_values=len(current_modules)
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user == self.author:
            modules_raw = self.values
            new_modules = []
            db_keys = [x[0] for x in self.current_modules]

            for module in modules_raw:
                idx = db_keys.index(module)
                new_modules.append(self.current_modules[idx])

            await self.config.guild(interaction.guild).set_raw(str(self.gamemode), "current_modules", value=new_modules)
            await interaction.response.send_message("Order changed.")
            self.view.stop()
        else:
            await interaction.response.send_message(
                "Only the author of the original message can interact with this component.",
                ephemeral=True
            )

class Hypixel(commands.Cog, MixinMeta, metaclass=CompositeMetaClass):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=365911945565569036, force_registration=True)
        self.session = aiohttp.ClientSession()

        self.autostats_tasks = {
            s.value: {} for s in scope
        }

        default_global = {
            "header_color": [255, 0, 0]
        }

        default_user = {
            "apikey": None,
            "header_color": None,
            "skin": None,
            "uuid": None,
        }

        gamemode_data = {}
        for gm in gamemodes:
            if gm == gamemodes.BEDWARS: # default modules for bedwars
                gamemode_data[str(gm.value)] = {
                    "current_modules": [
                        ("games_played_bedwars", "Games played"),
                        ("kills_bedwars", "Kills"),
                        ("normal_kd", "KD"),
                        ("beds_broken_bedwars", "Beds broken"),
                        ("wins_bedwars", "Wins"),
                        ("winstreak", "Winstreak"),
                        ("final_kills_bedwars", "Final kills"),
                        ("final_kd", "Final KD")
                    ],
                    "custom_modules": {
                        "wl_rate": "round((gamemode_stats['wins_bedwars'] / gamemode_stats['losses_bedwars']), 2)",
                        "normal_kd": "round((gamemode_stats['kills_bedwars'] / gamemode_stats['deaths_bedwars']), 2)",
                        "final_kd": "round((gamemode_stats['final_kills_bedwars'] / gamemode_stats['final_deaths_bedwars']), 2)",
                    },
                }
            else: # no defaults present for the rest (mainly because i never played them)
                gamemode_data[str(gm.value)] = {
                    "current_modules": [],
                    "custom_modules": {},
                }

        default_guild = {
            "apikey": None,
            "header_color": [255, 0, 0],
            **gamemode_data
        }

        self.config.register_global(**default_global)
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        asyncio.create_task(self.fetch_modules())


    """Commands"""
    @commands.guild_only()
    @commands.group(name="autostats", invoke_without_command=True)
    async def command_autostats(self, ctx: commands.Context, gm: gamemodes, *usernames: str) -> None:
        """Base command for autostats processes"""
        user_data = await self.username_list_to_data(ctx, gm, usernames)

        current_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "current_modules")
        custom_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "custom_modules")
        apikey, key_scope = await self.fetch_apikey(ctx)

        if key_scope == scope.GUILD:
            if len(self.autostats_tasks[key_scope.value]) >= 5:
                await ctx.send("Already 5 autostats tasks running on the guild apikey. "
                               f"Set your own apikey using `{ctx.clean_prefix}hypixelset apikey`")
                return

        autostats_task = Autostats(
            self,
            ctx.channel,
            gm,
            user_data,
            apikey,
            current_modules,
            custom_modules
        )

        self.autostats_tasks[key_scope.value][ctx.author.id] = autostats_task
        await autostats_task.start()

    @command_autostats.group(name="stop", invoke_without_command=True)
    async def command_autostats_stop(self, ctx: commands.Context) -> None:
        """Stop you current autostats process"""
        for s in scope:
            if ctx.author.id in self.autostats_tasks[s.value].keys():
                await self.autostats_tasks[s.value][ctx.author.id].cancel()
                del self.autostats_tasks[s.value][ctx.author.id]
                await ctx.tick()
                return

        await ctx.send("No running autostats tasks")

    @command_autostats_stop.command(name="all")
    async def command_autostats_stop_all(self, ctx: commands.Context, stop_scope: scope = True) -> None:
        """Stop all autostats processes"""
        if self.bot.is_owner(ctx.author) or ctx.guild.owner == ctx.author:
            if stop_scope == scope.GUILD:
                for task in self.autostats_tasks[stop_scope.value].values():
                    await task.cancel()

        if self.bot.is_owner(ctx.author):
            for task in self.autostats_tasks[stop_scope.value].values():
                await task.cancel()

    @commands.command(name="gamemodes")
    async def command_gamemodes(self, ctx) -> None:
        """Lists all available gamemodes"""
        await ctx.maybe_send_embed("\n".join([gm.value.db_key for gm in gamemodes]))

    @commands.group(name="hypixelset")
    async def command_hypixelset(self, ctx: commands.Context) -> None:
        pass

    @commands.dm_only()
    @command_hypixelset.command(name="apikey")
    async def command_hypixelset_apikey(self, ctx: commands.Context, apikey: str, guild: discord.Guild = None) -> None:
        resp, status = await request_hypixel(ctx=ctx, topic="key", apikey=apikey, session=self.session)

        if status == 200 and resp:
            if not guild:
                await self.config.user(ctx.author).apikey.set(apikey)
            else:
                await self.config.guild(guild).apikey.set(apikey)

            await ctx.tick()

        elif status == 403 and resp["cause"] == INVALID_API_KEY:
            await ctx.send("This apikey doesn't seem to be valid!")

    @command_hypixelset.command(name="color", aliases=["colour"])
    async def command_hypixelset_color(self, ctx: commands.Context, color: str, type: colortypes = None) -> None:
        """Custom header color"""
        try:
            if type:
                color = ImageColor.getrgb(f"{type.value}{color}")
            else:
                color = ImageColor.getrgb(color)
        except ValueError:
            await ctx.send("Color couldn't be found")
            return

        await self.config.user(ctx.author).header_color.set(list(color))

    @commands.guild_only()
    @commands.guildowner_or_permissions(administrator=True, manage_guild=True)
    @command_hypixelset.group(name="modules")
    async def command_hypixelset_modules(self, ctx: commands.Context) -> None:
        """Base command for managing modules"""
        pass

    @command_hypixelset_modules.command(name="add")
    async def command_hypixelset_modules_add(self, ctx: commands.Context, gm: gamemodes, db_key: str, *, clear_name: str) -> None:
        """Add a module for the given gamemode"""
        guild_data = await self.config.guild(ctx.guild).get_raw(str(gm))

        current_modules = guild_data["current_modules"]
        custom_modules = guild_data["custom_modules"]

        if db_key in self.all_modules[gm.db_key] or db_key in custom_modules.keys():
            if db_key in [x[0] for x in current_modules]:
                await ctx.send(f"This module is already added.")
                return

            current_modules.append((db_key, clear_name))
            await self.config.guild(ctx.guild).set_raw(str(gm), "current_modules", value=current_modules)
            await ctx.send(f"Module `{db_key}` added as `{clear_name}`")
        else:
            await ctx.send(f"Module `{db_key}` doesn't seem to be valid.\n"
                           f"Use `{ctx.clean_prefix}hypixelset modules list {gm.db_key}` to retrieve a list of supported ones")

    @command_hypixelset_modules.command(name="remove")
    async def command_hypixelset_modules_remove(self, ctx: commands.Context, gm: gamemodes, db_key: str = None, *, clear_name: str = None) -> None:
        """Remove a module for the given gamemode"""
        if not db_key and not clear_name:
            await ctx.send_help()
            return

        current_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "current_modules")
        db_keys = [x[0] for x in current_modules]
        clear_names = [x[1] for x in current_modules]

        if db_key in db_keys:
            idx = db_keys.index(db_key)
            db_keys.pop(idx)
            clear_names.pop(idx)

        if clear_name in clear_names:
            idx = clear_names.index(clear_name)
            clear_names.pop(idx)
            db_keys.pop(idx)

        if len(db_keys) != len(current_modules):
            current_modules = [(x, clear_names[idx]) for idx, x in enumerate(db_keys)]
            await self.config.guild(ctx.guild).set_raw(str(gm), "current_modules", value=current_modules)
            await ctx.tick()
        else:
            await ctx.send("No matching module found to remove")

    @command_hypixelset_modules.command(name="reorder")
    async def command_hypixelset_modules_reorder(self, ctx: commands.Context, gm: gamemodes) -> None:
        current_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "current_modules")

        view = discord.ui.View()
        view.add_item(SelectionRow(current_modules, ctx.author, self.config, gm))

        await ctx.send("Select the modules in your preferred order: ", view=view)

    @command_hypixelset_modules.command(name="list")
    async def command_hypixelset_modules_list(self, ctx: commands.Context, gm: gamemode) -> None:
        """List all modules of a gamemode"""
        custom_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "custom_modules")

        modules_gamemode = self.all_modules[gm.db_key] + [x[0] for x in custom_modules]
        modules_gamemode = "\n".join(list(map(str, modules_gamemode)))

        await ctx.send(file=discord.File(BytesIO(modules_gamemode.encode()), "modules.txt"))

    @commands.guild_only()
    @command_hypixelset.command(name="username", aliases=["name"])
    async def command_hypixelset_username(self, ctx: commands.Context, username: str) -> None:
        resp, status = await request_mojang(username, session=self.session)
        if status == 200 and resp.get("id", None):
            await self.config.user(ctx.author).uuid.set(resp["id"])
            await ctx.tick()

    @commands.guild_only()
    @commands.command(name="stats")
    async def command_stats(self, ctx, gm: gamemodes, *usernames: str) -> None:
        async with ctx.typing():
            user_data = await self.username_list_to_data(ctx, gm=gm, username_list=usernames)

            im_list = []
            for user in user_data:
                im_list.append(await self.create_stats_img(user, gm))

            await self.maybe_send_images(ctx.channel, im_list)

    @commands.command(name="tstats")
    async def command_tstats(self, ctx):
        active_modules = [
            ("wins_bedwars", "Wins"),
            ("kills_bedwars", "Kills"),
            ("final_kills_bedwars", "Final Kills"),
            ("beds_broken_bedwars", "Beds Broken"),
            ("kills_per_game", "Kills/Game"),
            ("losses_bedwars", "Losses"),
            ("deaths_bedwars", "Deaths"),
            ("final_deaths_bedwars", "Final Deaths"),
            ("beds_lost_bedwars", "Beds Lost"),
            ("final_kills_per_game", "Finals/Game"),
            ("win_loose_rate", "WLR"),
            ("kill_death_rate", "KDR"),
            ("final_kill_death_rate", "FKDR"),
            ("beds_destroyed_lost_rate", "BDLR"),
            ("beds_per_game", "Beds/Game"),
        ]
        custom_modules = {
            "kills_per_game": "round(gamemode_stats['kills_bedwars'] / gamemode_stats['games_played_bedwars'], 2)",
            "final_kills_per_game": "round(gamemode_stats['final_kills_bedwars'] / gamemode_stats['games_played_bedwars'], 2)",
            "win_loose_rate": "round(gamemode_stats['games_played_bedwars'] / gamemode_stats['wins_bedwars'], 2)",
            "kill_death_rate": "round(gamemode_stats['kills_bedwars'] / gamemode_stats['deaths_bedwars'], 2)",
            "final_kill_death_rate": "round(gamemode_stats['final_kills_bedwars'] / gamemode_stats['final_deaths_bedwars'], 2)",
            "beds_destroyed_lost_rate": "round(gamemode_stats['beds_broken_bedwars'] / gamemode_stats['beds_lost_bedwars'], 2)",
            "beds_per_game": "round(gamemode_stats['beds_broken_bedwars'] / gamemode_stats['games_played_bedwars'], 2)",
        }

        async with ctx.typing():
            user_data = await self.username_list_to_data(
                ctx,
                gamemode=gamemodes.BEDWARS,
                username_list=["sucr_kolli"],
                active_modules=active_modules,
                custom_modules=custom_modules,
            )

            await self.maybe_send_images(ctx.channel, [await self.create_stats_img_new(user_data[0], gamemodes.BEDWARS)])

    """Converters"""
    async def username_list_to_data(
            self,
            ctx,
            gm: gamemode,
            username_list: list,
            active_modules: list = None,
            custom_modules: dict = None,
    ) -> list:
        if ctx.guild:
            guild_data = await self.config.guild(ctx.guild).all()
            if not active_modules:
                active_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "current_modules")
            if not custom_modules:
                custom_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "custom_modules")
        else:
            guild_data = None
            header_color = tuple(await self.config.header_color())

        if not username_list:
            username_list = [str(ctx.author.id)]

        user_data = []
        failed = []
        async for username in AsyncIter(username_list):
            #trying a direct request first
            if 16 >= len(username) >= 3:
                uuid_resp, status = await request_mojang(username, session=self.session)
                if uuid_resp and status == 200:
                    try:
                        data, xp, username = await self.uuid_to_stats(uuid_resp["id"], gm, active_modules, custom_modules, ctx=ctx)

                        user_data.append({
                            "stats": data,
                            "header_color": tuple(guild_data["header_color"]) if guild_data else header_color,
                            "username": username,
                            "uuid": uuid_resp["id"],
                            "skin": None,
                            "xp": xp
                        })
                        continue
                    except ValueError:
                        pass
                    except KeyError:
                        pass

            #if it fails, try to convert the username to a discord.User object
            try:
                user_obj = await commands.UserConverter().convert(ctx, username)
                user_conf = await self.config.user(user_obj).all()

                if not user_conf["uuid"]:
                    failed.append(username)
                    continue

                data, xp, username = await self.uuid_to_stats(user_conf["uuid"], gm, active_modules, custom_modules, ctx=ctx)
                user_data.append({
                    "stats": data,
                    "header_color": (tuple(user_conf["header_color"])
                                     if user_conf["header_color"]
                                     else tuple(guild_data["header_color"])
                                        if guild_data["header_color"]
                                        else header_color),
                    "username": username,
                    "uuid": user_conf["uuid"],
                    "skin": user_conf["skin"],
                    "xp": xp
                })

            except commands.BadArgument:
                failed.append(username)

        if failed:
            text = box("\n".join(failed))
            await ctx.send("Stats for the following users couldn't be fetched. "
                           "Make sure a username is set if you pass a discord user. \n\n"
                            f"{text}")

        return user_data

    async def uuid_to_stats(self,
                            uuid: str,
                            gm: gamemode,
                            active_modules: list,
                            custom_modules: dict,
                            ctx: commands.Context = None,
                            apikey: str = None) -> Optional[Tuple[List, Any, Any]]:
        if not apikey:
            apikey, _ = await self.fetch_apikey(ctx)
        resp, status = await request_hypixel(ctx=ctx, uuid=uuid, apikey=apikey, session=self.session)
        if status == 200 and resp:
            gamemode_data = resp["player"]["stats"][gm.db_key]

            stats = []
            for module in active_modules:
                if module[0] in custom_modules.keys():
                    value = self.calculate_custom_value(custom_modules[module[0]], gamemode_data)
                else:
                    value = gamemode_data.get(module[0], 0)
                stats.append((str(module[1]), str(value)))

            return stats, gamemode_data[gm.xp_key], resp["player"]["playername"]

        else:
            return [], 0, ""


    """Dpy Events"""
    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        if self.command_hypixelset in [ctx.command, ctx.command.root_parent]:
            return

        user_key = await self.config.user(ctx.author).apikey()
        if not ctx.guild and not user_key:
            await ctx.send("No personal apikey set!")
            raise commands.CheckFailure()

        elif not user_key and not await self.config.guild(ctx.guild).apikey():
            await ctx.send("No personal or guild apikey set!")
            raise commands.CheckFailure()

    def cog_unload(self) -> None:
        asyncio.create_task(self.cog_unload_task())

    async def cog_unload_task(self) -> None:
        for s in scope:
            for task in self.autostats_tasks[s.value].values():
                await task.cancel()

        await self.session.close()


    """Image gen"""
    async def create_stats_img_new(self, user_data: dict, gm: gamemode):
        datapath: pathlib.Path = cog_data_path(self)
        background_path: pathlib.Path = datapath / "backgrounds"

        background = random.choice([file for file in background_path.iterdir() if file.is_file()])
        im_background = Image.open(background).convert("RGB")
        im_background = ImageEnhance.Brightness(im_background).enhance(0.3)
        im_background = im_background.filter(ImageFilter.GaussianBlur(im_background.width / 300))

        font_path = self.fetch_font(datapath, "arial")

        draw = ImageDraw.Draw(im_background, "RGBA")

        # top box
        font = ImageFont.truetype(str(font_path), size=40)
        x_top = (im_background.width * 0.02, im_background.width * 0.98)
        y_top = (im_background.height * 0.02, im_background.height * 0.22)

        draw.rounded_rectangle([(x_top[0], y_top[0]), (x_top[1], y_top[1])], fill=(0, 0, 0, 120), radius=20)
        draw.text(
            (x_top[0], (y_top[1] / 2 - y_top[0])),
            font=font,
            text=user_data["username"],
            anchor="lm",
        )

        # stats box
        font = ImageFont.truetype(str(font_path), size=20)
        x = (x_top[0], im_background.width * 0.7)
        y = (im_background.height * 0.25, im_background.height * 0.92)
        draw.rounded_rectangle([(x[0], y[0]), (x[1], y[1])], fill=(0, 0, 0, 120), radius=20)

        colors = [(0, 200, 0, 255), (200, 0, 0, 255), (0, 0, 200, 255), (0, 200, 200, 255)]

        start_x = (x[0] + im_background.width / 50)
        spacing_x = (x[1] - x[0]) / 3
        pos_x = start_x

        start_y = y[0] + im_background.width / 100
        spacing_y = (y[1] - y[0]) / int(len(user_data["stats"]) / 3)
        pos_y = [start_y + spacing_y * x for x in range(int(len(user_data["stats"]) / 3))]

        for idx, module in enumerate(user_data["stats"]):
            if idx < (len(user_data["stats"]) / 3):
                color = colors[0] if (idx + 1) % int(len(user_data["stats"]) / 3) else colors[3]
            elif idx < (len(user_data["stats"]) / 3) * 2:
                pos_x = start_x + spacing_x
                color = colors[1] if (idx + 1) % int(len(user_data["stats"]) / 3) else colors[3]
            elif idx >= (len(user_data["stats"]) / 3) * 2:
                pos_x = start_x + spacing_x * 2
                color = colors[2] if (idx + 1) % int(len(user_data["stats"]) / 3) else colors[3]

            draw.text(
                (pos_x, pos_y[idx % int(len(user_data["stats"]) / 3)]),
                text=f"{module[1]}",
                font=font,
                anchor="lt",
                fill=color,
            )
            draw.text(
                (pos_x + font.getlength(module[1] + " "), pos_y[idx % int(len(user_data["stats"]) / 3)]),
                text=f"{module[0]}",
                font=font,
                anchor="lt",
            )

        # skin box
        x_skin = (im_background.width * 0.72, x_top[1])
        draw.rounded_rectangle([(x_skin[0], y[0]), (x_skin[1], y[1])], fill=(0, 0, 0, 120), radius=20)

        pos = random.choice([
            (-25, -25, 20, 5, -2, -20, 2),
            (-25, 25, 20, 5, -2, 20, -2),
            (-5, 25, 10, 5, -2, 5, -5),
            (-5, -25, 10, 5, -2, -5, 5),
            (0, 0, 0, 0, 0, 0, 0),
        ])
        im_skin = await MinePI.render_3d_skin(
            user_data["uuid"],
            *pos,
            12,
            True,
            True,
            False,
            skin_image=user_data["skin"]
        )

        height = y[1] - y[0] - im_background.height / 25
        width = im_skin.width * (height / im_skin.height)
        im_skin = im_skin.resize((int(width), int(height)))
        im_background = im_background.convert("RGBA")

        x_pos_skin = int((x_skin[0] + (x_skin[1] - x_skin[0]) / 2) - im_skin.width / 2)
        y_pos_skin = int((y[0] + (y[1] - y[0]) / 2) - im_skin.height / 2)
        im_background.alpha_composite(im_skin, (x_pos_skin, y_pos_skin))

        return im_background

    async def create_stats_img(self, user_data: dict, gm: gamemode, compare_stats: list = None) -> Image.Image:
        datapath: pathlib.Path = cog_data_path(self)
        background_path: pathlib.Path = datapath / "backgrounds"

        color_header_stats = (255, 145, 0)
        color_body_stats = (255, 200, 0)

        # take care of the background image
        def background_im():
            background = random.choice([file for file in background_path.iterdir() if file.is_file()])
            im_background = Image.open(background).convert("RGBA")
            im_background = ImageEnhance.Brightness(im_background).enhance(0.3)
            im_background = im_background.filter(ImageFilter.GaussianBlur(im_background.width / 300))
            return im_background

        im_background = await self.bot.loop.run_in_executor(
            None,
            background_im
        )

        pos = random.choice([
            (-25, -25, 20, 5, -2, -20, 2),
            (-25, 25, 20, 5, -2, 20, -2),
            (-5, 25, 10, 5, -2, 5, -5),
            (-5, -25, 10, 5, -2, -5, 5),
            (0, 0, 0, 0, 0, 0, 0),
        ])
        im_skin = await MinePI.render_3d_skin(
            user_data["uuid"],
            *pos,
            12,
            True,
            True,
            False,
            skin_image=user_data["skin"]
        )

        def generate_image(im_skin):
            # fetch available fonts
            font_header_player_path = self.fetch_font(datapath, "header_player")
            font_header_stats_path = self.fetch_font(datapath, "header_stats")
            font_body_stats_path = self.fetch_font(datapath, "body_stats")

            font_header_player = ImageFont.truetype(str(font_header_player_path), int(im_background.height / 6.5))
            font_header_stats = ImageFont.truetype(str(font_header_stats_path), int(im_background.height / 8))

            modules_left = int(len(user_data["stats"]) / 2 + 1) if len(user_data["stats"]) % 2 else int(len(user_data["stats"]) / 2)

            height = int(im_background.height / 1.4)
            width = int(height * (im_skin.width / im_skin.height))
            im_skin = im_skin.resize((width, height), resample=Image.BOX)

            if len(user_data["stats"]) > 5:
                x = int((im_background.width / 2) - (im_skin.width / 2))
                stats_box = (
                    im_background.width / 2 - im_skin.width / 2 - im_background.width / 15,
                    im_background.height - (font_header_player.size * 2)
                )
            else:
                x = int(im_background.width - (im_skin.width * 1.5))
                stats_box = (
                    im_background.width - im_skin.width - im_skin.width * 1.5 - im_background.width / 25,
                    im_background.height - (font_header_player.size * 2)
                )

            im_background.alpha_composite(im_skin, (x, int(im_background.height / 6.5) + int(im_background.height / 200)))
            draw = ImageDraw.Draw(im_background)

            y_pos = []

            spacing = stats_box[1] / modules_left
            if modules_left % 2:
                for i in range(int(modules_left / 2) + 1):
                    y_pos.append(stats_box[1] / 2 + spacing * i)
                    if i:
                        y_pos.append(stats_box[1] / 2 - spacing * i)
            else:
                for i in range(int(modules_left / 2)):
                    y_pos.append(stats_box[1] / 2 + spacing * 0.5 + spacing * i)
                    y_pos.append(stats_box[1] / 2 - spacing * 0.5 - spacing * i)

            y_pos = sorted(y_pos)

            longest_item = max([x[0] for x in user_data["stats"]], key=len)
            length = font_header_stats.getlength(longest_item)
            if length > stats_box[0]:
                font_size = font_header_stats.size * (stats_box[0] / length)
                del font_header_stats
                font_header_stats = ImageFont.truetype(str(font_header_stats_path), int(font_size))

            font_body_stats = ImageFont.truetype(str(font_body_stats_path), int(font_header_stats.size * 0.95))

            draw.text(
                ((im_background.width / 2), im_background.height / 100),
                user_data["username"],
                fill=user_data["header_color"],
                font=font_header_player,
                anchor="mt"
            )
            anchor = "lm"
            compare_anchor = "rm"
            x = int(im_background.width / 25)
            compare_x = stats_box[0]
            header_margin = int(font_header_player.size + im_background.height / 100)
            for i in range(0, len(user_data["stats"])):
                try:
                    y = y_pos[i] + header_margin
                except IndexError:
                    y = y_pos[i - modules_left] + header_margin

                if i == modules_left:
                    anchor = "rm"
                    compare_anchor = "lm"
                    # compare_x = (im_background.width - stats_box[0]) + x + im_skin.width / 2
                    compare_x = stats_box[0] + im_skin.width * 1.5 + x
                    # print(stats_box[0], im_background.width, im_skin.width, x, compare_x)
                    # print(im_background.width - im_skin.width)
                    x = int(im_background.width * 0.96)

                draw.text(
                    (x, y),
                    user_data["stats"][i][0],
                    fill=color_header_stats,
                    font=font_header_stats,
                    anchor=anchor
                )

                draw.text(
                    (x, y + font_header_stats.size * 0.9),
                    user_data["stats"][i][1],
                    fill=color_body_stats,
                    font=font_body_stats,
                    anchor=anchor
                )

                if compare_stats:
                    compare_value, compare_color = self.get_compare_value_and_color(
                        user_data["stats"][i],
                        compare_stats[i][1]
                    )

                    draw.text(
                        (compare_x, y + font_header_stats.size * 0.9),
                        compare_value,
                        fill=compare_color,
                        font=font_body_stats,
                        anchor=compare_anchor
                    )

            xp_bar_im = self.render_xp_bar(gm, user_data["xp"], im_background.size)
            im_background.alpha_composite(xp_bar_im, (0, 0))

        await self.bot.loop.run_in_executor(
            None,
            generate_image,
            im_skin
        )

        return im_background

    def fetch_font(self, path: pathlib.Path, query: str) -> pathlib.Path:
        path = path / "fonts"
        for file in path.iterdir():
            if file.is_file() and query in file.stem:
                return file
        else:
            raise ValueError(f"Font {query} not found.")

    def get_compare_value_and_color(self, module: tuple, original_value: Union[Any]) -> Tuple[Any, Optional[Tuple]]:
        try:
            float(module[1])
        except ValueError:
            return module[1], None

        green = (0, 255, 0)
        red = (255, 0, 0)
        negative_list = [
            "loss"
        ]
        compare = float(module[1]) - float(original_value)
        compare = int(compare) if compare % 1 == 0 else round(compare, 2)

        if compare == 0:
            return str(compare), None

        elif compare < 0:
            for i in negative_list:
                if module[0] in i:
                    return str(compare), green
            return str(compare), red

        else:
            for i in negative_list:
                if module[0] in i:
                    return str(compare), red
            return str(compare), green

    def get_level_bedwars(self, xp: int) -> Tuple[int, float]:
        def xp_for_level():
            if level == 0:
                return 0

            respected_level = level_respecting_prestige()

            if respected_level > easy_levels:
                return 5000
            else:
                return level_scale.get(respected_level, 0)

        def level_respecting_prestige():
            if level > (highest_prestige * levels_per_prestige):
                return level - (highest_prestige * levels_per_prestige)
            else:
                return level % levels_per_prestige

        easy_levels = 4
        level_scale = {1: 500, 2: 1000, 3: 2000, 4: 3500, 5: 5000}
        easy_levels_xp = sum(level_scale.values())
        xp_per_prestige = 96 * 5000 + easy_levels_xp
        levels_per_prestige = 100
        highest_prestige = 10

        prestiges = int(xp / xp_per_prestige)
        level = prestiges * levels_per_prestige
        xp_without_prestige = xp - (prestiges * xp_per_prestige)

        for i in range(1, easy_levels + 1):
            xp_for_easy_level = xp_for_level()
            if xp_without_prestige < xp_for_easy_level:
                break

            level += 1
            xp_without_prestige -= xp_for_easy_level

        level_total = int(level + xp_without_prestige / 5000)
        if level_total % 100 > 4:
            xp_for_easy_level = 5000
        percentage = (level + xp_without_prestige / xp_for_easy_level) % 1.0
        return level_total, percentage

    def get_level_skywars(self, xp: int) -> Tuple[int, float]:
        xps = [0, 20, 70, 150, 250, 500, 1000, 2000, 3500, 5000, 10000, 15000]
        easy_xp_skywars = 0
        for i in xps:
            easy_xp_skywars += i
        if xp >= 15000:
            level = (xp - 15000) / 10000 + 12
            percentage = level % 1.0
            return int(level), percentage
        else:
            for i in range(len(xps)):
                if xp < xps[i]:
                    level = i + float(xp - xps[i - 1]) / (xps[i] - xps[i - 1])
                    percentage = level % 1.0
                    return int(level), percentage

    def render_xp_bar(self, gm: gamemode, xp: int, size: tuple):
        im = Image.new("RGBA", size)
        draw = ImageDraw.Draw(im)

        level, percentage = getattr(self, f"get_level_{gm.db_key.lower()}")(xp)

        line_thickness = int(size[1] / 216)
        spacing = int(size[1] / 54)
        x = int(size[0] / 7)
        y = int(size[1] - size[1] / 21) + spacing
        bar_color = "#40D433"
        line_color = "#9E9E9E"

        draw.line(
            ((x, y - spacing * 0.5), (x + (size[0] - x * 2), y - spacing * 0.5)),
            fill=line_color,
            width=spacing
        )
        draw.line(
            ((x, y - spacing * 0.5), (x + ((size[0] - x * 2) * percentage), y - spacing * 0.5)),
            fill=bar_color,
            width=spacing
        )

        draw.line(
            ((x, y), (size[0] - x, y)),
            fill=0,
            width=line_thickness
        )
        draw.line(
            ((x, y - spacing), (size[0] - x, y - spacing)),
            fill=0,
            width=line_thickness
        )

        for i in range(19):
            x_grid = x + i * ((size[0] - x * 2) / 18)
            draw.line(
                ((x_grid, y), (x_grid, y - spacing)),
                fill=0,
                width=line_thickness
            )

        font_size = int(size[1] / 20)
        font_xp_path = self.fetch_font(cog_data_path(self), "xp")
        font_xp = ImageFont.truetype(str(font_xp_path), font_size)

        draw.text(
            (size[0] / 2, y - spacing * 1.4),
            text=str(level),
            font=font_xp,
            fill=bar_color,
            anchor="mb"
        )

        return im

    """Utility functions"""
    def calculate_custom_value(self, custom_module: str, gamemode_stats: dict) -> Union[float, int]:
        try:
            return eval(custom_module)
        except KeyError:
            return 0

    async def fetch_apikey(self, ctx: commands.Context) -> Tuple[Optional[str], scope]:
        """Guild/User based apikey lookup"""
        user_key = await self.config.user(ctx.author).apikey()
        if not user_key and ctx.guild:
            guild_key = await self.config.guild(ctx.guild).apikey()
            return guild_key, scope.GLOBAL
        else:
            return user_key, scope.USER

    async def fetch_modules(self) -> None:
        """Fetch all available hypixel modules"""
        headers = {
            "USER_AGENT": USER_AGENT
        }

        async with self.session.get(
            "https://raw.githubusercontent.com/HypixelDatabase/HypixelTracking/master/API/player.json",
            headers=headers,
        ) as resp:
            if resp.status == 200:
                resp = json.loads(await resp.text())

        self.all_modules = {}
        for gamemode, modules in resp["player"]["stats"].items():
            self.all_modules[gamemode] = [x for x in modules.keys() if isinstance(x, str) or isinstance(x, int)]

    async def maybe_send_images(self, channel: discord.TextChannel, im_list: List[Image.Image]) -> List[discord.Message]:
        """Try to send a list of images to the given channel
        Warns if a permission error occurs"""
        def generate_im_list():
            im_binary_list = []

            for idx, im in enumerate(im_list):
                with BytesIO() as imb:
                    im.save(imb, "PNG")
                    imb.seek(0)
                    im_binary_list.append(discord.File(imb, f"stats{idx}.png"))

            return im_binary_list

        im_binary_list = await self.bot.loop.run_in_executor(
            None,
            generate_im_list
        )

        messages = []
        for i in range(0, len(im_binary_list), 10):
            try:
                messages.append(await channel.send(files=im_binary_list[i: i + 10]))
            except discord.Forbidden:
                messages.append(await channel.send("Looks like i do not have the proper permission to send attachments to this channel"))

        return messages

