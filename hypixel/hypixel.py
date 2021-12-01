import aiohttp
import asyncio
import math
import discord
import json
import MinePI
import pathlib
import random
import re
import time
import tabulate
import shutil

from io import BytesIO
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageColor
from typing import Optional, Tuple, Final, Union, List, Any, Literal

from redbot.core import commands, Config
from redbot.core.utils import AsyncIter
from redbot.core.data_manager import cog_data_path, bundled_data_path
from redbot.core.utils.chat_formatting import box

from .utils.abc import CompositeMetaClass, MixinMeta
from .utils.enums import Gamemode, Gamemodes, Scope, ColorTypes, Ranks, Rank

INVALID_API_KEY: Final = "Invalid API key"
USER_AGENT: Final = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36"


class ButtonConfirm(discord.ui.View):
    def __init__(self, author_id: int):
        self.author_id = author_id
        self.confirm = False
        super().__init__(timeout=30)

    def stop(self):
        self.clear_items()
        super().stop()

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.author_id == interaction.user.id:
            self.confirm = True
            self.stop()
        else:
            await interaction.response.send_message("You do not have permissions to do that...", ephemeral=True)

    @discord.ui.button(label="No", style=discord.ButtonStyle.red)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.author_id == interaction.user.id:
            self.stop()
        else:
            await interaction.response.send_message("You do not have permissions to do that...", ephemeral=True)


class SelectionRow(discord.ui.Select):
    def __init__(self, modules: dict, author: discord.Member, config: Config, gm: Gamemode):
        self.config = config
        self.gamemode = gm
        self.author = author
        self.all_modules = modules
        self.modules = modules[author.guild.id][str(gm)]

        options = []
        for module in self.modules:
            options.append(discord.SelectOption(label=module.name, description=module.db_key))

        super().__init__(
            placeholder="Select the modules in the order you want...",
            options=options,
            min_values=len(self.modules),
            max_values=len(self.modules)
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user == self.author:
            new_modules = []
            names = [module.name for module in self.modules]
            for v in self.values:
                idx = names.index(v)
                new_modules.append(self.modules[idx])

            self.all_modules[interaction.guild.id][str(self.gamemode)] = new_modules
            new_modules = [(module.db_key, module.name) for module in self.modules]

            await self.config.guild(interaction.guild).set_raw(
                str(self.gamemode), "current_modules", value=new_modules
            )

            await interaction.response.send_message("Order changed.")
            self.view.stop()
        else:
            await interaction.response.send_message(
                "Only the author of the original message can interact with this component.",
                ephemeral=True
            )


class Module:
    """Class representing a single module"""
    all_modules: Optional[dict] = None
    custom_modules: Optional[dict] = None

    def __init__(
            self,
            name: str,
            db_key: str = None,
            calc: str = None,
            gm: Gamemode = None,
    ):
        self._name: str = name
        self._db_key: Optional[str] = db_key
        self._calc: Optional[str] = calc
        self._gamemode: Optional[Gamemode] = gm
    
    @property
    def name(self):
        return self._name
    
    @property
    def db_key(self):
        return self._db_key

    @property
    def is_custom(self):
        return bool(self._calc)
    
    @property
    def calculation(self):
        return self._calc

    @property
    def gamemode(self):
        return self._gamemode

    def get_value(self, player: Optional[Any] = None, stats: Optional[dict] = None):
        stats = stats if not player else player.stats(self._gamemode)
        if not stats:
            return

        if not self.is_custom:
            return stats.get(self._db_key, 0)

        try:
            calc = re.sub("{}", f"{stats=}".split("=")[0], self._calc)
            return eval(calc)
        except KeyError:
            return 0


class Player:
    """Class representing a single hypixel player"""
    session: Optional[aiohttp.ClientSession] = None
    config: Optional[Config] = None

    def __init__(
            self,
            ctx: commands.Context,
            user_identifier: Union[str, discord.Member],
    ):
        self._ctx = ctx
        self._user_identifier = user_identifier
        self._player_ready: asyncio.Event = asyncio.Event()

        self._guild = ctx.guild
        self._uuid: Optional[str] = None
        self._user: Optional[discord.Member] = None
        self._skin: Optional[Image.Image] = None
        self._xp: Optional[int] = None
        self._resp: Optional[dict] = None
        self._color: Optional[Tuple] = None
        self._rank: Optional[Ranks] = Ranks.DEFAULT
        self._valid: bool = False

        self._apikey: Optional[str] = None
        self._apikey_scope: Optional[Scope] = None

        ctx.bot.loop.create_task(self.initialize())

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
                resp_dict = json.loads(await resp.text())
                return resp_dict, resp.status
            except json.JSONDecodeError:
                # invalid response?
                return None, resp.status
            except asyncio.TimeoutError:
                # api down again?
                return None, None

    @classmethod
    async def fetch_apikey(cls, ctx: commands.Context) -> Tuple[Optional[str], Scope]:
        """Guild/User based apikey lookup"""
        user_key = await Player.config.user(ctx.author).apikey()
        if not user_key and ctx.guild:
            guild_key = await Player.config.guild(ctx.guild).apikey()
            return guild_key, Scope.GLOBAL
        else:
            return user_key, Scope.USER

    @property
    def rank(self):
        """Returns the player's Hypixel rank"""
        return self._rank

    @property
    def skin(self):
        """Returns the player's raw skin"""
        return self._skin

    @property
    def name(self):
        if self._resp:
            return self._resp.get("playername", str(self._user_identifier))

    @property
    def uuid(self):
        """Returns the UUID associated to this object"""
        return self._uuid

    @property
    def valid(self):
        """Returns True if there is a UUID associated to this object"""
        return self._valid

    async def wait_for_fully_constructed(self):
        """Returns true as soon as the object is fully constructed"""
        await self._player_ready.wait()

    def xp(self, gm: Gamemode = None) -> Tuple[int, float]:
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

                return levels, xp / cost

            elif gm == Gamemodes.SKYWARS.value:
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
            xp = self._resp.get("networkExp", 0)
            fraction, level = math.modf(math.sqrt((2 * xp) + 30625) / 50 - 2.5)
            return int(level), fraction
        else:
            return 0, 0

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

    async def initialize(self):
        await self.get_uuid()
        if not bool(self._uuid):
            self._player_ready.set()
            return

        self._apikey, self._apikey_scope = await self.fetch_apikey(self._ctx)

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

    async def get_uuid(self):
        if isinstance(self._user_identifier, discord.Member) or len(self._user_identifier) == 18:
            try:
                member_obj = await commands.MemberConverter().convert(self._ctx, str(self._user_identifier))
                self._user = member_obj
                uuid = await Player.config.user(member_obj).uuid()
                if uuid:
                    self._uuid = uuid
                    return

            except commands.BadArgument:
                pass

        else:
            # no MemberObject or ID was passed or the given user has no uuid set
            # trying a request to mojang servers
            resp, status = await Player.request_mojang(self._user_identifier)

            if status == 200 and resp.get("id", None):
                # request successful, using the uuid returned
                self._uuid = resp["id"]
            else:
                # request not successful, trying to convert the rest
                try:
                    member_obj = await commands.MemberConverter().convert(self._ctx, str(self._user_identifier))

                    uuid = await Player.config.user(member_obj).uuid()
                    if uuid:
                        self._user = member_obj
                        self._uuid = uuid
                        return

                except commands.BadArgument:
                    pass

    async def fetch_stats(self):
        if not self._uuid:
            return

        resp, status = await Player.request_hypixel(
            apikey=self._apikey,
            uuid=self._uuid,
        )

        if status == 200 and resp and resp["success"]:
            self._resp = resp["player"] if resp["player"] else {}

    async def fetch_user_data(self):
        if isinstance(self._user, discord.Member):
            member_data = await Player.config.user(self._user).all()
            self._skin = member_data["skin"]
            self._color = member_data["header_color"]

        else:
            self._color = await Player.config.header_color()

        self._rank = Ranks.convert(self._resp)


class Autostats:
    def __init__(self,
                 cog,
                 channel: discord.TextChannel,
                 gm: Gamemodes,
                 users: list,
                 ):
        self.channel: discord.TextChannel = channel
        self.gamemode: Gamemodes = gm
        self.users = users
        self.cog: Hypixel = cog
        self.messages: list = []

        self.last_updated: Optional[int] = None
        self.task: Optional[asyncio.Task] = None

    @staticmethod
    def _exception_catching_callback(task: asyncio.Task):
        if task.exception():
            task.result()

    async def is_updated(self):
        user = self.users[0]
        prev = user.stats(self.gamemode)
        await user.fetch_stats()
        if user.stats(self.gamemode)[self.gamemode.autostats_key] != prev[self.gamemode.autostats_key]:
            return True

        return False

    def timeout(self):
        if time.time() > self.last_updated + 3600:
            return True
        return False

    async def main(self):
        try:
            while not self.task.cancelled():
                first_previous = self.users[0].stats(self.gamemode)
                if self.timeout():
                    await self.cancel()
                if await self.is_updated():
                    self.last_updated = int(time.time())
                    await self.maybe_delete_old_messages()
                    im_list = []

                    for user in self.users:
                        previous = user.stats(self.gamemode)
                        await user.fetch_stats()

                        im_list.append(await self.cog.create_stats_img(
                            player=user,
                            gm=self.gamemode,
                            compare_stats=first_previous if first_previous else previous
                        ))
                        first_previous = None

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

    async def start(self):
        self.last_updated = int(time.time())
        im_list = await asyncio.gather(*[self.cog.create_stats_img(user, self.gamemode) for user in self.users])

        self.messages = await self.cog.maybe_send_images(self.channel, im_list)

        self.task = asyncio.create_task(self.main())
        self.task.add_done_callback(self._exception_catching_callback)

    async def cancel(self):
        await self.maybe_delete_old_messages()
        self.task.cancel()
        del self


class Hypixel(commands.Cog, MixinMeta, metaclass=CompositeMetaClass):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=365911945565569036, force_registration=True)
        self.session = aiohttp.ClientSession()
        self.cog_ready_event = asyncio.Event()
        self.modules = {}

        Player.session = self.session
        Player.config = self.config

        self.autostats_tasks = {
            s.value: {} for s in Scope
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
        for gm in Gamemodes:
            if gm == Gamemodes.BEDWARS: # default modules for bedwars
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
                        "wl_rate": "round(({}['wins_bedwars'] / {}['losses_bedwars']), 2)",
                        "normal_kd": "round(({}['kills_bedwars'] / {}['deaths_bedwars']), 2)",
                        "final_kd": "round(({}['final_kills_bedwars'] / {}['final_deaths_bedwars']), 2)",
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

        bot.loop.create_task(self.initialize())

    async def initialize(self):
        self.cog_ready_event.clear()
        data_path = cog_data_path(self)

        for path in bundled_data_path(self).iterdir():
            path = path.name
            if not (data_path / path).exists():
                (data_path / path).mkdir()

            for file in (bundled_data_path(self) / path).iterdir():
                if file.is_file():
                    try:
                        shutil.copy(str(file), str(data_path / path))
                    except shutil.Error:
                        pass
            # shutil.rmtree(str(bundled_data_path(self) / path))

        Module.all_modules = await self.fetch_modules()

        async for guild in AsyncIter(self.bot.guilds):
            guild_data = await self.config.guild(guild).all()
            self.modules[guild.id] = {}
            for gm in Gamemodes:
                self.modules[guild.id][str(gm.value)] = []
                active_modules = guild_data[str(gm.value)]["current_modules"]
                custom_modules = guild_data[str(gm.value)]["custom_modules"]

                for db_key, name in active_modules:
                    if db_key in custom_modules.keys():
                        self.modules[guild.id][str(gm.value)].append(
                            Module(
                                name=name,
                                db_key=db_key,
                                calc=custom_modules[db_key],
                                gm=gm.value,
                            )
                        )
                    else:
                        self.modules[guild.id][str(gm.value)].append(
                            Module(
                                name=name,
                                db_key=db_key,
                                gm=gm.value,
                            )
                        )

        self.cog_ready_event.set()

    """Commands"""
    @commands.guild_only()
    @commands.group(name="autostats", invoke_without_command=True)
    async def command_autostats(self, ctx: commands.Context, gm: Gamemodes, *usernames: str) -> None:
        """Automatically sends your stats

        Automatically updates the stats image sent to discord after each round
        This is still a heavy WIP. Since hypixel only updates their api as soon
        as a game ends, stats can sometimes be messed up

        **Args**:
            **gm**: The gamemode you want to get stats for
            **usernames**: a single or multiple discord Members or minecraft names

        Example use:
            `[p]autostats bedwars`
            `[p]autostats bedwars Technoblade sucr_kolli`
        """
        if gm not in [gm.value for gm in Gamemodes if gm.value.autostats_key]:
            await ctx.send("The given gamemode currently isn't supported for autostats")
            return

        async with ctx.typing():
            usernames = usernames if usernames else [ctx.author]
            users = [Player(ctx, user_identifier) for user_identifier in usernames]
            await asyncio.gather(*[user.wait_for_fully_constructed() for user in users])

            _, key_scope = await Player.fetch_apikey(ctx)

            if key_scope == Scope.GUILD:
                if len(self.autostats_tasks[key_scope.value]) >= 5:
                    await ctx.send("Already 5 autostats tasks running on the guild apikey. "
                                   f"Set your own apikey using `{ctx.clean_prefix}hypixelset apikey`")
                    return

            if all([user.valid for user in users]):
                autostats_task = Autostats(
                    self,
                    ctx.channel,
                    gm,
                    users,
                )

                self.autostats_tasks[key_scope.value][ctx.author.id] = autostats_task
                await autostats_task.start()
            else:
                failed = []
                for user in users:
                    if not user.valid:
                        failed.append(user)
                await self.send_failed_for(ctx, failed)

    @command_autostats.group(name="stop", invoke_without_command=True)
    async def command_autostats_stop(self, ctx: commands.Context) -> None:
        """Stops your current autostats process"""
        for s in Scope:
            if ctx.author.id in self.autostats_tasks[s.value].keys():
                await self.autostats_tasks[s.value][ctx.author.id].cancel()
                del self.autostats_tasks[s.value][ctx.author.id]
                await ctx.tick()
                return

        await ctx.send("No running autostats tasks")

    @command_autostats_stop.command(name="all")
    async def command_autostats_stop_all(self, ctx: commands.Context, stop_scope: Scope = True) -> None:
        """Stops all autostats processes"""
        if self.bot.is_owner(ctx.author) or ctx.guild.owner == ctx.author:
            if stop_scope == Scope.GUILD:
                for task in self.autostats_tasks[stop_scope.value].values():
                    await task.cancel()

        if self.bot.is_owner(ctx.author):
            for task in self.autostats_tasks[stop_scope.value].values():
                await task.cancel()

    @commands.command(name="gamemodes")
    async def command_gamemodes(self, ctx) -> None:
        """Lists all available gamemodes"""
        await ctx.maybe_send_embed("\n".join([gm.value.db_key for gm in Gamemodes]))

    @commands.group(name="hypixelset")
    async def command_hypixelset(self, ctx: commands.Context) -> None:
        """Base command for cog settings"""
        pass

    @commands.dm_only()
    @command_hypixelset.command(name="apikey")
    async def command_hypixelset_apikey(self, ctx: commands.Context, apikey: str, *, guild: discord.Guild = None) -> None:
        """Api key management for the hypixel api

        Keys are managed server wide and on a user basis
        If `guild` is given, the key is set for the whole guild
        else the key is treated as a personal one and only used for you

        Api keys can be obtained by typing `/api` on the hypixel minecraft server

        **Arguments**:
            **apikey**: your hypixel api key
            **guild**: guild to set the apikey for

        Example use:
            `[p]hypixelset apikey <your_key>`
            `[p]hypixelset apikey <your_key> 133049272517001216`
        """
        resp, status = await Player.request_hypixel(topic="key", apikey=apikey)

        if status == 200 and resp:
            if not guild:
                await self.config.user(ctx.author).apikey.set(apikey)
                await ctx.tick()
            else:
                member = guild.get_member(ctx.author)
                if member or await self.bot.is_owner(ctx.author):
                    if await self.bot.is_owner(ctx.author) or member.guild_permissions.manage_guild:
                        await self.config.guild(guild).apikey.set(apikey)
                        await ctx.tick()
                    else:
                        await ctx.send("Sorry, looks like you do not have proper permissions to set an apikey "
                                       f"for the guild {guild.name}. Ask a server moderator to do so.")
                else:
                    await ctx.send(f"You do not appear to be a member of {guild.name}")

        elif status == 403 and resp["cause"] == INVALID_API_KEY:
            await ctx.send("This apikey doesn't seem to be valid!")

    @commands.guild_only()
    @commands.guildowner_or_permissions(administrator=True, manage_guild=True)
    @command_hypixelset.group(name="modules", aliases=["module"])
    async def command_hypixelset_modules(self, ctx: commands.Context) -> None:
        """Base command for managing modules"""
        pass

    @command_hypixelset_modules.command(name="add")
    async def command_hypixelset_modules_add(self, ctx: commands.Context, gm: Gamemodes, db_key: str, *, clear_name: str) -> None:
        """Add a module for the given gamemode"""
        guild_data = await self.config.guild(ctx.guild).get_raw(str(gm))

        custom_modules = guild_data["custom_modules"]

        modules = self.modules[ctx.guild.id][str(gm)]
        if not (db_key in Module.all_modules[str(gm)] or db_key in custom_modules.keys()):
            await ctx.send(f"The given database key (`{db_key}`) doesn't seem to be a "
                           f"valid default nor custom one. You can list all available ones by typing "
                           f"`{ctx.clean_prefix}hypixelset modules list {gm.db_key}` first.")
            return

        if db_key in [module.db_key for module in modules]:
            await ctx.send(f"The given database key (`{db_key}`) is already added. Remove it by typing "
                           f"`{ctx.clean_prefix}hypixelset modules remove {db_key}` first.")
            return

        if clear_name in [module.name for module in modules]:
            await ctx.send(f"The given module name (`{clear_name}`) is already added. Remove it by typing "
                           f"`{ctx.clean_prefix}hypixelset modules remove {clear_name}` first.")
            return

        self.modules[ctx.guild.id][str(gm)].append(
            Module(
                name=clear_name,
                db_key=db_key,
                calc=custom_modules[db_key] if db_key in custom_modules.keys() else None,
                gm=gm,
            )
        )
        guild_data["current_modules"].append((db_key, clear_name))
        await self.config.guild(ctx.guild).set_raw(
            str(gm), "current_modules", value=guild_data["current_modules"]
        )

        await ctx.tick()

    @command_hypixelset_modules.command(name="create")
    async def command_hypixelset_modules_create(self, ctx: commands.Context, gm: Gamemodes, db_key: str, *, calc: str) -> None:
        """Create a new custom module for the given gamemode"""
        custom_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "custom_modules")
        all_modules = Module.all_modules[gm.db_key] + list(custom_modules.keys())

        if db_key in all_modules:
            await ctx.send("The given db_key seems to be in use already.")
            return

        for module in Module.all_modules[gm.db_key]:
            print(module)
            pattern = re.compile(f"[{module}]")
            calc = pattern.sub(f"{{}}['{module}']", calc)

        print(calc)

    @command_hypixelset_modules.command(name="list")
    async def command_hypixelset_modules_list(self, ctx: commands.Context, *, gm: Gamemodes) -> None:
        """List all modules of a gamemode"""
        custom_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "custom_modules")

        modules_gamemode = Module.all_modules[gm.db_key] + list(custom_modules.keys())
        modules_gamemode = "\n".join(list(map(str, modules_gamemode)))

        await ctx.send(file=discord.File(BytesIO(modules_gamemode.encode()), "modules.txt"))

    @command_hypixelset_modules.command(name="remove")
    async def command_hypixelset_modules_remove(self, ctx: commands.Context, gm: Gamemodes, db_key: str = None, *, clear_name: str = None) -> None:
        """Remove a module for the given gamemode"""
        if not db_key and not clear_name:
            await ctx.send_help()
            return

        current_modules = await self.config.guild(ctx.guild).get_raw(str(gm), "current_modules")
        modules = self.modules[ctx.guild.id][str(gm)]

        for idx, module in enumerate(modules):
            if db_key == module.db_key or clear_name == module.name:
                self.modules[ctx.guild.id][str(gm)].pop(idx)
                current_modules.pop(idx)
                await self.config.guild(ctx.guild).set_raw(
                    str(gm), "current_modules", value=current_modules
                )
                await ctx.tick()
                return
        else:
            await ctx.send("No matching module found. You can list all modules by typing "
                           f"`{ctx.clean_prefix}hypixelset modules list {gm.db_key}`")

    @command_hypixelset_modules.command(name="reorder")
    async def command_hypixelset_modules_reorder(self, ctx: commands.Context, *, gm: Gamemodes) -> None:
        """Reorder modules"""
        view = discord.ui.View()
        view.add_item(SelectionRow(self.modules, ctx.author, self.config, gm))

        await ctx.send("Select the modules in your preferred order: ", view=view)

    @commands.guild_only()
    @command_hypixelset.command(name="username", aliases=["name"])
    async def command_hypixelset_username(self, ctx: commands.Context, username: str) -> None:
        """Bind your minecraft account to your discord account

        Why this is useful? You UUID is stored. Thus people can mention you
        to see your stats. Passing discord members instead of minecraft usernames
        spares one request and thus speeds all other commands up

        **Args**:
            **username**: Your minecraft username

        Example Use:
            `[p]hypixelset username sucr_kolli`

        Example how it can be used afterwards:
            Bedwars stats without specifying a username:
            `[p]stats bedwars`
            Bedwars stats for Benno if he bound an MC account already:
            `[p]stats bedwars @Benno`
        """

        async with ctx.typing():
            resp, status = await Player.request_mojang(username)
            if status == 200 and resp.get("id", None):
                embed = discord.Embed(
                    color=await ctx.embed_color(), title="Is that you?"
                )
                skin = await MinePI.render_3d_skin(resp["id"], ratio=8)
                embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar)
                embed.add_field(name="Name", value=username, inline=False)
                embed.add_field(name="UUID", value=resp["id"], inline=False)
                embed.set_footer(text="Hypixel stats bot")
                embed.set_thumbnail(url=f"attachment://skin_{ctx.author.name}.png")

                with BytesIO() as imb:
                    skin.save(imb, "PNG")
                    imb.seek(0)
                    file = discord.File(imb, f"skin_{ctx.author.name}.png")

                view = ButtonConfirm(ctx.author.id)

                msg = await ctx.send(embed=embed, file=file, view=view)

                await view.wait()
                await msg.edit(view=None)
                if view.confirm:
                    await self.config.user(ctx.author).uuid.set(resp["id"])
                    await ctx.send("Username successfully set!")
                else:
                    await ctx.send("Cancelled")
            else:
                await ctx.send("The given username doesn't seem to be valid.")


    @commands.guild_only()
    @commands.command(name="stats")
    async def command_stats(self, ctx, gm: Gamemodes, *usernames: str) -> None:
        """Stats for the given gamemode

        Get a players stats for a hypixel gamemode

        **Args**:
            **gm**: The gamemode you want to get stats for
            **usernames**: a single or multiple discord Members or minecraft names

        Example use:
            `[p]stats bedwars`
            `[p]stats bedwars Technoblade sucr_kolli`
        """
        if not usernames:
            usernames = [ctx.author]

        async with ctx.typing():
            users = []
            for username in usernames:
                users.append(Player(
                    ctx,
                    username,
                ))

            await asyncio.gather(*[user.wait_for_fully_constructed() for user in users])
            im_list = []
            failed = []
            for user in users:
                if not user.valid:
                    failed.append(user)
                else:
                    im_list.append(await self.create_stats_img(user, gm))

            await self.maybe_send_images(ctx.channel, im_list)

        if failed:
            await self.send_failed_for(ctx, failed)

    @commands.command(name="tstats")
    async def command_tstats(self, ctx, user: str = None):
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
            "kills_per_game": "round({}['kills_bedwars'] / {}['games_played_bedwars'], 2)",
            "final_kills_per_game": "round({}['final_kills_bedwars'] / {}['games_played_bedwars'], 2)",
            "win_loose_rate": "round({}['games_played_bedwars'] / {}['wins_bedwars'], 2)",
            "kill_death_rate": "round({}['kills_bedwars'] / {}['deaths_bedwars'], 2)",
            "final_kill_death_rate": "round({}['final_kills_bedwars'] / {}['final_deaths_bedwars'], 2)",
            "beds_destroyed_lost_rate": "round({}['beds_broken_bedwars'] / {}['beds_lost_bedwars'], 2)",
            "beds_per_game": "round({}['beds_broken_bedwars'] / {}['games_played_bedwars'], 2)",
        }

        modules = []
        for module in active_modules:
            if module[0] in custom_modules.keys():
                modules.append(
                    Module(
                        module[1],
                        module[0],
                        calc=custom_modules[module[0]],
                        gm=Gamemodes.BEDWARS.value,
                    )
                )
            else:
                modules.append(
                    Module(
                        module[1],
                        db_key=module[0],
                        gm=Gamemodes.BEDWARS.value,
                    )
                )

        async with ctx.typing():
            user = Player(
                ctx,
                user if user else ctx.author,
            )

            await user.wait_for_fully_constructed()
            if user.valid:
                im = await self.create_stats_img_new(user, gm=Gamemodes.BEDWARS.value, modules=modules)
                await self.maybe_send_images(ctx.channel, [im])
            else:
                await self.send_failed_for(ctx, [user])


    """Dpy Events"""
    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        if self.command_hypixelset in [ctx.command, ctx.command.root_parent]:
            return

        user_key = await self.config.user(ctx.author).apikey()
        if not ctx.guild and not user_key:
            await ctx.send("No personal apikey set!")
            raise commands.CheckFailure()

        elif not user_key and not await self.config.guild(ctx.guild).apikey():
            await ctx.send("No personal or guild apikey set!\n"
                           f"Run `{ctx.clean_prefix}help hypixelset apikey` in DMs to learn more.")
            raise commands.CheckFailure()

        await self.cog_ready_event.wait()

    def cog_unload(self) -> None:
        asyncio.create_task(self.cog_unload_task())

    async def cog_unload_task(self) -> None:
        for s in Scope:
            for task in self.autostats_tasks[s.value].values():
                await task.cancel()

        await self.session.close()

    async def red_delete_data_for_user(
        self,
        *,
        requester: Literal["discord", "owner", "user", "user_strict"],
        user_id: int,
    ):
        await self.config.user_from_id(user_id).clear()


    """Image gen"""
    async def create_stats_img_new(self, player: Player, gm: Gamemode, modules: list):
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
        y_text = y_top[1] / 2 + y_top[0]
        x_text = x_top[0] + im_background.width * 0.02
        if player.rank != Ranks.DEFAULT:
            pattern = re.compile("[+]")
            text = f"[{pattern.sub('', player.rank.value.clear_name)}"
            draw.text(
                (x_text, y_text),
                font=font,
                text=text,
                anchor="lm",
                fill=player.rank.value.color
            )
            x_text += font.getlength(text)

            for _ in range(0, len(pattern.findall(player.rank.value.clear_name))):
                draw.text(
                    (x_text, y_text),
                    font=font,
                    text="+",
                    anchor="lm",
                    fill=player.rank.value.plus_color
                )
                x_text += font.getlength("+")

            draw.text(
                (x_text, y_text),
                font=font,
                text=f"]",
                anchor="lm",
                fill=player.rank.value.color
            )
            x_text += font.getlength("]" + " ")

        draw.text(
            (x_text, y_text),
            font=font,
            text=player.name.upper(),
            anchor="lm",
            fill=player.rank.value.color,
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
        spacing_y = (y[1] - y[0]) / int(len(modules) / 3)
        pos_y = [start_y + spacing_y * x for x in range(int(len(modules) / 3))]

        for idx, module in enumerate(modules):
            if idx < (len(modules) / 3):
                color = colors[0] if (idx + 1) % int(len(modules) / 3) else colors[3]
            elif idx < (len(modules) / 3) * 2:
                pos_x = start_x + spacing_x
                color = colors[1] if (idx + 1) % int(len(modules) / 3) else colors[3]
            elif idx >= (len(modules) / 3) * 2:
                pos_x = start_x + spacing_x * 2
                color = colors[2] if (idx + 1) % int(len(modules) / 3) else colors[3]

            val = str(module.get_value(player))
            draw.text(
                (pos_x, pos_y[idx % int(len(modules) / 3)]),
                text=val,
                font=font,
                anchor="lt",
                fill=color,
            )
            draw.text(
                (pos_x + font.getlength(val + " "), pos_y[idx % int(len(modules) / 3)]),
                text=module.name,
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
            player.uuid,
            *pos,
            12,
            True,
            True,
            False,
            skin_image=player.skin
        )

        height = y[1] - y[0] - im_background.height / 25
        width = im_skin.width * (height / im_skin.height)
        im_skin = im_skin.resize((int(width), int(height)))
        im_background = im_background.convert("RGBA")

        x_pos_skin = int((x_skin[0] + (x_skin[1] - x_skin[0]) / 2) - im_skin.width / 2)
        y_pos_skin = int((y[0] + (y[1] - y[0]) / 2) - im_skin.height / 2)
        im_background.alpha_composite(im_skin, (x_pos_skin, y_pos_skin))

        return im_background

    async def create_stats_img(self, player: Player, gm: Gamemode, compare_stats: list = None) -> Image.Image:
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
            player.uuid,
            *pos,
            12,
            True,
            True,
            False,
            skin_image=player.skin
        )

        modules = self.modules[player._ctx.guild.id][str(gm)]
        def generate_image(im_skin):
            # fetch available fonts
            font_header_player_path = self.fetch_font(datapath, "header_player")
            font_header_stats_path = self.fetch_font(datapath, "header_stats")
            font_body_stats_path = self.fetch_font(datapath, "body_stats")

            font_header_player = ImageFont.truetype(str(font_header_player_path), int(im_background.height / 6.5))
            font_header_stats = ImageFont.truetype(str(font_header_stats_path), int(im_background.height / 8))

            modules_left = int(len(modules) / 2 + 1) if len(modules) % 2 else int(len(modules) / 2)

            height = int(im_background.height / 1.4)
            width = int(height * (im_skin.width / im_skin.height))
            im_skin = im_skin.resize((width, height), resample=Image.BOX)

            if len(modules) > 5:
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

            draw.text(
                ((im_background.width / 2), im_background.height / 100),
                player.name,
                fill=player.rank.value.color,
                font=font_header_player,
                anchor="mt"
            )

            if modules_left:
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

                longest_item = max([x.name for x in modules], key=len)
                length = font_header_stats.getlength(longest_item)
                if length > stats_box[0]:
                    font_size = font_header_stats.size * (stats_box[0] / length)
                    del font_header_stats
                    font_header_stats = ImageFont.truetype(str(font_header_stats_path), int(font_size))

                font_body_stats = ImageFont.truetype(str(font_body_stats_path), int(font_header_stats.size * 0.95))

                anchor = "lm"
                compare_anchor = "rm"
                x = int(im_background.width / 25)
                compare_x = stats_box[0]
                header_margin = int(font_header_player.size + im_background.height / 100)
                for i, module in enumerate(modules):
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
                        module.name,
                        fill=color_header_stats,
                        font=font_header_stats,
                        anchor=anchor
                    )

                    draw.text(
                        (x, y + font_header_stats.size * 0.9),
                        str(module.get_value(player)),
                        fill=color_body_stats,
                        font=font_body_stats,
                        anchor=anchor
                    )

                    if compare_stats:
                        compare_value, compare_color = self.get_compare_value_and_color(
                            module,
                            module.get_value(player),
                            compare_stats,
                        )

                        draw.text(
                            (compare_x, y + font_header_stats.size * 0.9),
                            compare_value,
                            fill=compare_color,
                            font=font_body_stats,
                            anchor=compare_anchor
                        )

            if gm.xp_key:
                xp_bar_im = self.render_xp_bar(gm, *player.xp(gm), im_background.size)
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

    def get_compare_value_and_color(
            self,
            module: Module,
            new_val: Optional[Union[int, float, str]],
            c_stats: dict
    ) -> Tuple[Any, Optional[Tuple]]:
        try:
            float(new_val)
        except ValueError:
            return new_val, None

        green = (0, 255, 0)
        red = (255, 0, 0)
        negative_list = [
            "loss"
        ]
        compare = new_val - module.get_value(stats=c_stats)
        compare = int(compare) if compare % 1 == 0 else round(compare, 2)

        if compare == 0:
            return str(compare), None

        elif compare < 0:
            for i in negative_list:
                if (module.db_key if not module.is_custom else module.name) in i:
                    return str(compare), green
            return str(compare), red

        else:
            for i in negative_list:
                if (module.db_key if not module.is_custom else module.name) in i:
                    return str(compare), red
            return str(compare), green

    def render_xp_bar(self, gm: Gamemode, level: int, percentage: float, size: tuple):
        im = Image.new("RGBA", size)
        draw = ImageDraw.Draw(im)

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

        all_modules = {}
        for gm, modules in resp["player"]["stats"].items():
            all_modules[gm] = [x for x in modules.keys() if isinstance(x, str) or isinstance(x, int)]

        return all_modules

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
                messages.append(
                    await channel.send(
                        "Looks like i do not have the proper permission to send attachments to this channel"
                    )
                )

        return messages

    async def send_failed_for(self, ctx: commands.Context, users: List):
        if len(users) == 1:
            if users[0]._user:
                msg = (f"Fetching stats for `{users[0]._user.name}` failed. Looks like the given discord user doesn't "
                       f"have a minecraft name set yet. Tell them do to so by running "
                       f"`{ctx.clean_prefix}hypixelset username`.")
            else:
                msg = f"Fetching stats for `{users[0]._user_identifier}` failed. "
                if users[0]._resp is None:
                    msg += "Retrieving data from the hypixel api failed."
                else:
                    msg += "Looks like this player never joined hypixel."
        else:
            msg = "Fetching stats for the following users failed: \n"

            failed = []
            for user in users:
                if user._user:
                    failed.append([user._user.name, "No MC name set"])
                else:
                    if not user.uuid:
                        reason = "Invalid MC name"
                    elif user._resp is None:
                        reason = "Request failed. API might be down"
                    else:
                        reason = "Never joined hypixel"

                    failed.append([f"{user._user_identifier}:", f"- {reason}"])

            msg += f"```yaml\n{tabulate.tabulate(failed, ['user', 'reason'])}\n```"

        await ctx.send(msg)

